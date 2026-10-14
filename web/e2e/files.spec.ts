import type { Page } from "@playwright/test";
import { answered, askWhereCodeRuns, expect, test } from "./fixtures";

const panel = (page: Page) => page.getByTestId("files-panel");
const toggle = (page: Page) => page.getByTestId("files-toggle");
const rows = (page: Page) => panel(page).getByTestId("file-row");
const row = (page: Page, path: string) => panel(page).locator(`[data-testid="file-row"][data-path="${path}"]`);
const detail = (page: Page) => panel(page).getByTestId("file-detail");

// Opens a conversation that has nothing in it, made through the server and titled, since the conversations of all the
// tests are listed on the side. Its code runs on this machine, so that there is something to make files.
async function openChat(page: Page, title: string): Promise<string> {
  const made = await page.request.post("/api/chats", { data: { title, code: { where: "local" } } });
  expect(made.status()).toBe(201);
  const id: string = (await made.json()).id;
  await page.goto(`/chat?id=${id}`);
  await expect(page.getByRole("button", { name: "Attach files" })).toBeEnabled();

  return id;
}

const attach = (page: Page, ...files: { name: string; content: string | Buffer }[]) =>
  page.getByTestId("file-input").setInputFiles(
    files.map(({ name, content }) => ({ name, mimeType: "application/octet-stream", buffer: typeof content === "string" ? Buffer.from(content) : content })),
  );

// Asks for the files that "code:files" writes, and waits for them, so that what the panel shows of each can be seen
async function withFiles(page: Page, title: string): Promise<string> {
  const id = await askWhereCodeRuns(page, `code:files ${title}`);
  await answered(page, "That is done: 1 step ran.", 30_000);
  await toggle(page).click();
  await expect(rows(page)).toHaveCount(5);

  return id;
}

test.describe("the files of a conversation", () => {
  test("none are there to begin with, and the panel says so, and opens and closes with its button", async ({ page }) => {
    await openChat(page, "Files: nothing yet");

    await expect(panel(page)).toHaveCount(0);
    await expect(toggle(page)).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByTestId("files-count")).toHaveCount(0);

    await toggle(page).click();
    await expect(toggle(page)).toHaveAttribute("aria-pressed", "true");
    await expect(panel(page).getByTestId("files-empty")).toContainText("No files yet");

    await toggle(page).click();
    await expect(panel(page)).toHaveCount(0);
    await expect(toggle(page)).toHaveAttribute("aria-pressed", "false");
  });

  test("a file that is attached is listed, with its folder and size, at once and without the page being opened again", async ({ page }) => {
    await openChat(page, "Files: what was attached");
    await toggle(page).click();
    await expect(panel(page).getByTestId("files-empty")).toBeVisible();

    await attach(page, { name: "data.csv", content: "a,b\n1,2\n" }, { name: "notes.txt", content: "A note.\n" });

    await expect(rows(page)).toHaveCount(2);
    await expect(row(page, "uploads/data.csv")).toContainText("data.csv");
    await expect(row(page, "uploads/data.csv")).toContainText("8 B");
    await expect(row(page, "uploads/notes.txt")).toContainText("notes.txt");
    await expect(panel(page).getByRole("region", { name: "uploads" })).toBeVisible();
    await expect(page.getByTestId("files-count")).toHaveText("2");
  });

  test("files that code makes come into the list as it makes them, by folder", async ({ page }) => {
    await openChat(page, "Files: what code made");
    await toggle(page).click();
    await expect(panel(page).getByTestId("files-empty")).toBeVisible();

    await page.getByRole("textbox", { name: "Message" }).fill("code:files while the list is open");
    await page.getByRole("button", { name: "Send" }).click();

    await expect(rows(page)).toHaveCount(5, { timeout: 30_000 });
    await expect(panel(page).getByTestId("files-empty")).toHaveCount(0);
    // What is at the top comes first, and is named as it is where there are folders as well
    await expect(panel(page).getByRole("heading", { level: 3 })).toHaveText(["Top level", "logs", "tables"]);
    await expect(rows(page)).toHaveText([/blob\.bin/, /empty\.txt/, /big\.log/, /long\.csv/, /wide\.tsv/]);
    await expect(row(page, "tables/long.csv")).toContainText("9.9 KB");
    await expect(page.getByTestId("files-count")).toHaveText("5");
  });

  test("a table is shown as one, from its first row, as far as is shown of it", async ({ page }) => {
    await openChat(page, "Files: a long table");
    await page.getByRole("textbox", { name: "Message" }).fill("code:files a long table");
    await page.getByRole("button", { name: "Send" }).click();
    await answered(page, "That is done: 1 step ran.", 30_000);
    await toggle(page).click();

    await row(page, "tables/long.csv").click();

    await expect(detail(page)).toContainText("long.csv");
    await expect(detail(page)).toContainText("tables");
    const table = detail(page).getByTestId("file-table");
    await expect(table.locator("thead th")).toHaveText(["gene", "score", "note"]);
    await expect(table.locator("tbody tr")).toHaveCount(200);
    await expect(table.locator("tbody tr").first().locator("td")).toHaveText(["G000", "0.00", "row 0, with a comma"]);
    await expect(detail(page)).toContainText("Only the start of the table is shown");
  });

  test("a table whose cells are divided by tabs is shown by them, and as many columns as fit are shown", async ({ page }) => {
    await withFiles(page, "tabs");

    await row(page, "tables/wide.tsv").click();

    const table = detail(page).getByTestId("file-table");
    await expect(table.locator("thead th")).toHaveCount(40);
    await expect(table.locator("thead th").first()).toHaveText("c0");
    await expect(table.locator("tbody tr")).toHaveCount(1);
    await expect(detail(page)).toContainText("Only the start of the table is shown");
  });

  test("text is shown from its start, and says how much of it is shown when it is longer", async ({ page }) => {
    await withFiles(page, "a long log");

    await row(page, "logs/big.log").click();

    const text = detail(page).getByTestId("file-text");
    await expect(text).toContainText("line 00000 xxxxxxxx");
    await expect(text).not.toContainText("line 07999");
    await expect(detail(page)).toContainText("Only the first 195 KB are shown");
  });

  test("a small text file is shown whole, with nothing said of what is left out", async ({ page }) => {
    await openChat(page, "Files: small text");
    await attach(page, { name: "notes.txt", content: "Line one\nLine two\n" });
    await expect(page.getByTestId("files-count")).toHaveText("1");
    await toggle(page).click();

    await row(page, "uploads/notes.txt").click();

    await expect(detail(page).getByTestId("file-text")).toHaveText("Line one\nLine two\n");
    await expect(detail(page)).not.toContainText("Only the first");
  });

  test("a file with nothing in it is said to be empty", async ({ page }) => {
    await withFiles(page, "empty");

    await row(page, "empty.txt").click();

    await expect(detail(page)).toContainText("This file is empty.");
  });

  test("a file that is not text, which a name says is, is not shown as text", async ({ page }) => {
    await openChat(page, "Files: not text");
    await attach(page, { name: "odd.txt", content: Buffer.from([137, 80, 78, 71, 0, 1, 2, 3]) });
    await expect(page.getByTestId("files-count")).toHaveText("1");
    await toggle(page).click();

    await row(page, "uploads/odd.txt").click();

    await expect(detail(page)).toContainText("This file is not text, so it cannot be shown here.");
    await expect(detail(page).getByTestId("file-text")).toHaveCount(0);
    await expect(detail(page).getByRole("link", { name: "Download" }).last()).toBeVisible();
  });

  test("a kind of file that cannot be shown can be saved, and is not offered to be opened in a tab", async ({ page }) => {
    const id = await withFiles(page, "binary");

    await row(page, "blob.bin").click();

    await expect(detail(page)).toContainText("This kind of file cannot be shown here.");
    await expect(detail(page).getByRole("link", { name: "Open in a new tab" })).toHaveCount(0);
    const save = detail(page).getByRole("link", { name: "Download" }).first();
    await expect(save).toHaveAttribute("href", `/api/chats/${id}/files/blob.bin?download=true`);
    const [download] = await Promise.all([page.waitForEvent("download"), save.click()]);
    expect(download.suggestedFilename()).toBe("blob.bin");
  });

  test("a file that the page can show can be opened in a tab, and saved under its name", async ({ page }) => {
    const id = await withFiles(page, "open and save");

    await row(page, "tables/long.csv").click();

    const open = detail(page).getByRole("link", { name: "Open in a new tab" });
    await expect(open).toHaveAttribute("href", `/api/chats/${id}/files/tables/long.csv`);
    await expect(open).toHaveAttribute("target", "_blank");
    await expect(open).toHaveAttribute("rel", /noopener/);
    const [download] = await Promise.all([page.waitForEvent("download"), detail(page).getByRole("link", { name: "Download" }).click()]);
    expect(download.suggestedFilename()).toBe("long.csv");
  });

  test("a picture is shown, and the way back to the list is there", async ({ page }) => {
    await askWhereCodeRuns(page, "code:plot a picture");
    await answered(page, "That is done: 1 step ran.", 30_000);
    await toggle(page).click();
    await expect(rows(page)).toHaveCount(2);

    await row(page, "plots/figure_1.png").click();

    const picture = detail(page).getByTestId("file-picture");
    await expect(picture).toBeVisible();
    await expect.poll(() => picture.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
    await expect(rows(page)).toHaveCount(0);

    await detail(page).getByRole("button", { name: "Back to the files" }).click();

    await expect(detail(page)).toHaveCount(0);
    await expect(rows(page)).toHaveCount(2);
  });

  test("files are found by what is typed of their path, which is asked for only where there are many", async ({ page }) => {
    await withFiles(page, "to find");
    await expect(panel(page).getByRole("searchbox", { name: "Find a file" })).toHaveCount(0);
    await attach(
      page,
      { name: "alpha.csv", content: "a\n1\n" },
      { name: "beta.csv", content: "a\n1\n" },
      { name: "gamma.txt", content: "g\n" },
    );
    await expect(rows(page)).toHaveCount(8);

    const find = panel(page).getByRole("searchbox", { name: "Find a file" });
    await find.fill("CSV uploads");
    await expect(rows(page)).toHaveText([/alpha\.csv/, /beta\.csv/]);
    await find.fill("tables long");
    await expect(rows(page)).toHaveCount(1);
    await find.fill("nothing like it");
    await expect(rows(page)).toHaveCount(0);
    await expect(panel(page)).toContainText("No file has that in its name.");
    await find.fill("");
    await expect(rows(page)).toHaveCount(8);
  });

  test("it is closed by its button, by Escape, and over a narrow page by touching what is behind it", async ({ page }) => {
    await openChat(page, "Files: closing");
    await toggle(page).click();
    await expect(panel(page)).toBeVisible();
    await panel(page).getByRole("button", { name: "Close the files" }).click();
    await expect(panel(page)).toHaveCount(0);

    await toggle(page).click();
    await expect(panel(page)).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(panel(page)).toHaveCount(0);

    await page.setViewportSize({ width: 720, height: 800 });
    await toggle(page).click();
    await expect(panel(page)).toBeVisible();
    // Over the conversation, so that it fills what it can of the page and covers the rest
    const box = await panel(page).boundingBox();
    expect(box?.x).toBeGreaterThan(300);
    expect((box?.x ?? 0) + (box?.width ?? 0)).toBeCloseTo(720, 0);
    await page.mouse.click(40, 400);
    await expect(panel(page)).toHaveCount(0);
  });

  test("it sits beside the conversation on a wide page, which keeps what room it has", async ({ page }) => {
    await openChat(page, "Files: beside");
    const transcript = page.getByTestId("transcript");
    const before = await transcript.boundingBox();

    await toggle(page).click();
    await expect(panel(page)).toBeVisible();

    const after = await transcript.boundingBox();
    const beside = await panel(page).boundingBox();
    expect(after?.width).toBeLessThan((before?.width ?? 0) - 300);
    expect((after?.x ?? 0) + (after?.width ?? 0)).toBeLessThanOrEqual((beside?.x ?? 0) + 1);
  });

  test("a list that cannot be got is said so, with the server's words", async ({ page }) => {
    await page.route("**/api/chats/*/files", (route) =>
      route.fulfill({ status: 500, json: { error: { code: "broken", message: "The files cannot be listed just now." } } }),
    );
    await openChat(page, "Files: a failed list");

    await toggle(page).click();

    await expect(panel(page).getByRole("alert")).toContainText("The files cannot be listed just now.");
    await expect(page.getByTestId("files-count")).toHaveCount(0);
  });

  test("a list that was being got when something changed is not said to have failed", async ({ page }) => {
    let asked = 0;
    // Nothing is answered, so that the list is being got for as long as the test looks
    await page.route("**/api/chats/*/files", () => {
      asked += 1;
    });
    await openChat(page, "Files: a list that went stale");
    await expect.poll(() => asked).toBe(1);

    await attach(page, { name: "notes.txt", content: "A note.\n" });
    await expect.poll(() => asked).toBe(2);
    await toggle(page).click();

    await expect(panel(page).getByRole("status", { name: "Loading the files" })).toBeVisible();
    await expect(panel(page).getByRole("alert")).toHaveCount(0);
  });

  test("code that runs again and again is followed by one asking for the list, not one for each run", async ({ page }) => {
    const made = await page.request.post("/api/chats", { data: { title: "Files: a burst of runs" } });
    expect(made.status()).toBe(201);
    const id: string = (await made.json()).id;
    const runs = 8;
    const told = (event: { kind: string; speaker?: string | null; text?: string; data?: Record<string, unknown> }, at: number) =>
      `event: chat\nid: ${at}\ndata: ${JSON.stringify({ id: at, turn: 1, speaker: null, text: "", data: {}, time: 0, ...event })}\n\n`;
    const events = [
      { kind: "user", speaker: "Human researcher", text: "Run it", data: { attachments: [] } },
      { kind: "tool_calls", speaker: "Principal Investigator", text: "Starting.", data: { calls: [{ id: "c1", name: "run_code", arguments: "{}" }] } },
      ...Array.from({ length: runs }, (_, run) => ({ kind: "cell", data: { call: "c1", language: "python", code: `${run}`, status: "ok" } })),
      { kind: "answer", speaker: "Principal Investigator", text: "All of them ran." },
    ];
    // The stream tells of one event each time the page asks for it, and the page asks again at once, so that the runs
    // come close together, which is what a lead that runs code in a loop does
    let streams = 0;
    await page.route("**/api/chats/*/events*", (route) => {
      const at = streams;
      streams += 1;

      return route.fulfill({
        status: 200,
        headers: { "content-type": "text/event-stream", "cache-control": "no-cache" },
        body: `retry: ${at < events.length ? 50 : 600_000}\n\n${at < events.length ? told(events[at], at + 1) : ""}`,
      });
    });
    let listed = 0;
    page.on("request", (request) => {
      if (request.method() === "GET" && /\/api\/chats\/[^/]+\/files(\?|$)/.test(request.url())) listed += 1;
    });

    await page.goto(`/chat?id=${id}`);
    await expect(page.getByTestId("lead-message").last()).toContainText("All of them ran.");
    await expect.poll(() => listed, { timeout: 10_000 }).toBeGreaterThanOrEqual(2);
    // Longer than it waits for things to be quiet, in which more asking would show
    await page.waitForTimeout(800);

    expect(listed).toBeLessThanOrEqual(3);
  });

  test("a file that cannot be read is said so, and the list is still there to go back to", async ({ page }) => {
    await openChat(page, "Files: a failed file");
    await attach(page, { name: "notes.txt", content: "A note.\n" });
    await expect(page.getByTestId("files-count")).toHaveText("1");
    await page.route("**/api/chats/*/files/uploads/notes.txt", (route) =>
      route.fulfill({ status: 404, json: { error: { code: "not_found", message: "There is no such file there." } } }),
    );
    await toggle(page).click();

    await row(page, "uploads/notes.txt").click();

    await expect(detail(page).getByRole("alert")).toContainText("There is no such file there.");
    await detail(page).getByRole("button", { name: "Back to the files" }).click();
    await expect(rows(page)).toHaveCount(1);
  });

  test("it is for the conversation it is opened in, and another has its own", async ({ page }) => {
    await openChat(page, "Files: the first");
    await attach(page, { name: "first.txt", content: "one\n" });
    await expect(page.getByTestId("files-count")).toHaveText("1");

    await openChat(page, "Files: the second");

    await expect(page.getByTestId("files-count")).toHaveCount(0);
    await toggle(page).click();
    await expect(panel(page).getByTestId("files-empty")).toBeVisible();
  });
});
