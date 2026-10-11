import { writeFileSync } from "node:fs";
import type { Page, TestInfo } from "@playwright/test";
import { answered, expect, HOME_HEADING, test } from "./fixtures";

const box = (page: Page) => page.getByRole("textbox", { name: "Message" });
const send = (page: Page) => page.getByRole("button", { name: "Send", exact: true });
const tray = (page: Page) => page.getByTestId("attachment-tray");
const chips = (page: Page) => tray(page).getByTestId("attachment");
const chosen = (page: Page, ...files: { name: string; content: string | Buffer }[]) =>
  page.getByTestId("file-input").setInputFiles(
    files.map(({ name, content }) => ({
      name,
      mimeType: "application/octet-stream",
      buffer: typeof content === "string" ? Buffer.from(content) : content,
    })),
  );

// A file on disk, which is what a person chooses from, to be chosen with its date
function onDisk(testInfo: TestInfo, name: string, content: string): string {
  const path = testInfo.outputPath(name);
  writeFileSync(path, content);

  return path;
}

// The server's limit on a file, from which the page refuses one that is larger (see e2e/scripted_server.py)
const LIMIT = 20 * 1024;

// Opens a conversation that has nothing in it, made through the server and titled, since the conversations of all the
// tests are listed on the side
async function openChat(page: Page, title: string): Promise<string> {
  const made = await page.request.post("/api/chats", { data: { title } });
  expect(made.status()).toBe(201);
  const id: string = (await made.json()).id;
  await page.goto(`/chat?id=${id}`);
  // The composer takes nothing until the conversation has been opened, which a file chosen before then would not be
  await expect(page.getByRole("button", { name: "Attach files" })).toBeEnabled();

  return id;
}

async function uploaded(page: Page, id: string): Promise<string[]> {
  const listed = await page.request.get(`/api/chats/${id}/files`);

  return (await listed.json()).files.map((file: { path: string }) => file.path);
}

test.describe("attaching files to a message", () => {
  test("a file that is chosen is sent at once, and goes with the message, which the lead is told of", async ({ page }) => {
    const id = await openChat(page, "Files: one file goes with the message");

    await chosen(page, { name: "data.csv", content: "a,b\n1,2\n" });

    await expect(chips(page)).toHaveCount(1);
    await expect(chips(page).first()).toHaveAttribute("data-status", "ready");
    await expect(chips(page).first()).toContainText("data.csv");
    await expect(chips(page).first()).toContainText("8 B");
    expect(await uploaded(page, id)).toContain("uploads/data.csv");
    // Nothing is left chosen in the input, so that the same file can be chosen again
    await expect(page.getByTestId("file-input")).toHaveValue("");

    // A message may be a file alone
    await expect(send(page)).toBeEnabled();
    await send(page).click();

    await expect(page.getByTestId("user-message")).toContainText("data.csv");
    await answered(page, "uploads/data.csv (8 bytes)");
    await expect(tray(page)).toHaveCount(0);
    await expect(send(page)).toBeDisabled();
  });

  test("a message can have words and several files, and the same file chosen twice is one", async ({ page }, testInfo) => {
    await openChat(page, "Files: several files and some words");
    // Files on disk, which have a date of their own, as a file chosen twice from a folder has
    const one = onDisk(testInfo, "one.txt", "1");
    const two = onDisk(testInfo, "two.txt", "22");
    const input = page.getByTestId("file-input");

    await input.setInputFiles([one, two]);
    await expect(chips(page)).toHaveCount(2);
    await input.setInputFiles(one);

    await expect(chips(page)).toHaveCount(2);
    await expect(chips(page).filter({ hasText: "one.txt" })).toHaveAttribute("data-status", "ready");
    await expect(chips(page).filter({ hasText: "two.txt" })).toHaveAttribute("data-status", "ready");

    await box(page).fill("Compare these");
    await box(page).press("Enter");

    await expect(page.getByTestId("user-message")).toContainText("one.txt");
    await expect(page.getByTestId("user-message")).toContainText("two.txt");
    await expect(page.getByTestId("user-message")).toContainText("Compare these");
    await answered(page, "uploads/two.txt (2 bytes)");
    await expect(page.getByTestId("lead-message")).toContainText("uploads/one.txt (1 bytes)");
  });

  test("a file with a name that is taken is kept under another, which is the name the message goes with", async ({ page }) => {
    const id = await openChat(page, "Files: a name that is taken");
    await chosen(page, { name: "same.txt", content: "first" });
    await expect(chips(page).first()).toHaveAttribute("data-status", "ready");
    await send(page).click();
    await answered(page, "uploads/same.txt");

    await chosen(page, { name: "same.txt", content: "second, which is another file" });

    await expect(chips(page).first()).toContainText("same (2).txt");
    expect(await uploaded(page, id)).toEqual(expect.arrayContaining(["uploads/same.txt", "uploads/same (2).txt"]));
  });

  test("a file that is chosen again after it was taken away is taken again", async ({ page }) => {
    await openChat(page, "Files: chosen again after it was taken away");
    await chosen(page, { name: "again.txt", content: "x" });
    await expect(chips(page)).toHaveCount(1);

    await page.getByRole("button", { name: "Remove again.txt" }).click();
    await expect(tray(page)).toHaveCount(0);
    await chosen(page, { name: "again.txt", content: "x" });

    await expect(chips(page)).toHaveCount(1);
    await expect(chips(page).first()).toHaveAttribute("data-status", "ready");
  });

  test("a file that is larger than the server takes is turned away with its size, and is not sent", async ({ page }) => {
    let sent = 0;
    await page.route("**/uploads?*", (route) => {
      sent += 1;
      return route.continue();
    });
    await openChat(page, "Files: one that is too large");

    await chosen(page, { name: "big.bin", content: Buffer.alloc(LIMIT + 1) }, { name: "small.txt", content: "ok" });

    await expect(page.getByRole("alert").filter({ hasText: "big.bin is larger than the 20 KB that can be attached" })).toBeVisible();
    await expect(chips(page)).toHaveCount(1);
    await expect(chips(page).first()).toContainText("small.txt");
    await expect(chips(page).first()).toHaveAttribute("data-status", "ready");
    expect(sent).toBe(1);

    // One exactly as large as is allowed is taken
    await chosen(page, { name: "exact.bin", content: Buffer.alloc(LIMIT) });
    await expect(chips(page).filter({ hasText: "exact.bin" })).toHaveAttribute("data-status", "ready");
  });

  test("a file the server turns away is shown with what it said, cannot be tried again, and holds the message up", async ({ page }) => {
    await page.route("**/uploads?*", (route) =>
      route.fulfill({ status: 413, json: { error: { code: "too_large", message: "The server did not want it" } } }),
    );
    await openChat(page, "Files: one the server turns away");

    await chosen(page, { name: "refused.txt", content: "x" });

    await expect(chips(page).first()).toHaveAttribute("data-status", "failed");
    await expect(chips(page).first()).toContainText("The server did not want it");
    await expect(page.getByRole("button", { name: "Retry refused.txt" })).toHaveCount(0);
    await box(page).fill("A message with a file that failed");
    await expect(send(page)).toBeDisabled();
    await expect(page.getByText("Retry or remove the file that failed")).toBeVisible();

    await page.getByRole("button", { name: "Remove refused.txt" }).click();

    await expect(tray(page)).toHaveCount(0);
    await expect(page.getByText("Retry or remove the file that failed")).toHaveCount(0);
    await expect(send(page)).toBeEnabled();
  });

  test("a file that was lost on the way can be sent again", async ({ page }) => {
    let tries = 0;
    await page.route("**/uploads?*", (route) => {
      tries += 1;
      return tries === 1 ? route.abort("failed") : route.continue();
    });
    const id = await openChat(page, "Files: one lost on the way");

    await chosen(page, { name: "lost.txt", content: "found" });

    await expect(chips(page).first()).toHaveAttribute("data-status", "failed");
    await expect(chips(page).first()).toContainText("The file could not be sent");
    await expect(send(page)).toBeDisabled();

    await page.getByRole("button", { name: "Retry lost.txt" }).click();

    await expect(chips(page).first()).toHaveAttribute("data-status", "ready");
    await expect(send(page)).toBeEnabled();
    expect(await uploaded(page, id)).toContain("uploads/lost.txt");
    expect(tries).toBe(2);
  });

  test("a file that is still going shows how far it has got and holds the message up until it is there", async ({ page }) => {
    await page.route("**/uploads?*", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1_500));
      await route.continue();
    });
    await openChat(page, "Files: one that takes its time");

    await chosen(page, { name: "slow.txt", content: "wait for it" });

    await expect(chips(page).first()).toHaveAttribute("data-status", "uploading");
    await expect(page.getByRole("progressbar", { name: "Uploading slow.txt" })).toBeVisible();
    await expect(page.getByRole("progressbar", { name: "Uploading slow.txt" })).toHaveAttribute("aria-valuenow", /^\d{1,3}$/);
    await box(page).fill("Waiting for the file");
    await expect(send(page)).toBeDisabled();
    await expect(page.getByText("Uploading a file…")).toBeVisible();

    await expect(chips(page).first()).toHaveAttribute("data-status", "ready");
    await expect(page.getByRole("progressbar")).toHaveCount(0);
    await expect(send(page)).toBeEnabled();
    await expect(page.getByText("Uploading a file…")).toHaveCount(0);
  });

  test("a file that is taken away while it is going is not shown again when it arrives", async ({ page }) => {
    await page.route("**/uploads?*", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1_000));
      await route.continue().catch(() => undefined);
    });
    const id = await openChat(page, "Files: one taken away on its way");

    await chosen(page, { name: "gone.txt", content: "x" });
    await expect(chips(page).first()).toHaveAttribute("data-status", "uploading");
    await page.getByRole("button", { name: "Remove gone.txt" }).click();

    await expect(tray(page)).toHaveCount(0);
    await page.waitForTimeout(1_500);
    await expect(tray(page)).toHaveCount(0);
    await expect(send(page)).toBeDisabled();
    await expect(page.getByText("Uploading a file…")).toHaveCount(0);
    // Calling it off stops it reaching the conversation, rather than only hiding it
    expect(await uploaded(page, id)).not.toContain("uploads/gone.txt");
  });

  test("a file that is still going when the page is left is not sent", async ({ page }) => {
    await page.route("**/uploads?*", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1_000));
      await route.continue().catch(() => undefined);
    });
    const id = await openChat(page, "Files: one left behind on its way");
    await chosen(page, { name: "left.txt", content: "x" });
    await expect(chips(page).first()).toHaveAttribute("data-status", "uploading");

    await page.getByRole("link", { name: "New chat" }).click();

    await expect(page.getByRole("heading", { name: HOME_HEADING })).toBeVisible();
    await page.waitForTimeout(1_500);
    expect(await uploaded(page, id)).not.toContain("uploads/left.txt");
  });

  test("files that are dropped on the composer are attached, and the composer shows that it will take them", async ({ page }) => {
    await openChat(page, "Files: dropped on the composer");
    const composer = page.locator("form").filter({ has: box(page) });

    const data = await page.evaluateHandle(() => {
      const transfer = new DataTransfer();
      transfer.items.add(new File(["dropped"], "dropped.txt", { type: "text/plain" }));

      return transfer;
    });
    await composer.dispatchEvent("dragover", { dataTransfer: data });
    await expect(composer).toHaveAttribute("data-dragging", "true");
    await composer.dispatchEvent("drop", { dataTransfer: data });

    await expect(composer).toHaveAttribute("data-dragging", "false");
    await expect(chips(page)).toHaveCount(1);
    await expect(chips(page).first()).toContainText("dropped.txt");
    await expect(chips(page).first()).toHaveAttribute("data-status", "ready");
  });

  test("what is dragged over the composer that is not a file is left alone", async ({ page }) => {
    await openChat(page, "Files: text dragged over the composer");
    const composer = page.locator("form").filter({ has: box(page) });

    const data = await page.evaluateHandle(() => {
      const transfer = new DataTransfer();
      transfer.setData("text/plain", "just words");

      return transfer;
    });
    await composer.dispatchEvent("dragover", { dataTransfer: data });
    await composer.dispatchEvent("drop", { dataTransfer: data });

    await expect(composer).toHaveAttribute("data-dragging", "false");
    await expect(tray(page)).toHaveCount(0);
  });

  test("a picture that is pasted is attached, and text that is pasted is not taken for a file", async ({ page }) => {
    await openChat(page, "Files: pasted");

    const paste = async (withText: boolean) => {
      const data = await page.evaluateHandle((text) => {
        const transfer = new DataTransfer();
        transfer.items.add(new File(["pixels"], "image.png", { type: "image/png" }));
        if (text) transfer.setData("text/plain", "a cell copied from a table");

        return transfer;
      }, withText);
      // Not dispatchEvent, which makes an event that has no clipboard
      await box(page).evaluate(
        (element, clipboardData) =>
          element.dispatchEvent(new ClipboardEvent("paste", { clipboardData, bubbles: true, cancelable: true })),
        data,
      );
    };

    await paste(true);
    await expect(tray(page)).toHaveCount(0);

    await paste(false);
    await expect(chips(page)).toHaveCount(1);
    await expect(chips(page).first()).toContainText("image.png");
    await expect(chips(page).first()).toHaveAttribute("data-status", "ready");
  });

  test("files chosen while the lead works wait for the next message", async ({ page }) => {
    await openChat(page, "Files: chosen while the lead works");
    await box(page).fill("slow: a reply while a file is chosen");
    await box(page).press("Enter");
    await expect(page.getByTestId("lead-message")).toContainText("word1 ");

    await chosen(page, { name: "next.txt", content: "for later" });

    await expect(chips(page).first()).toHaveAttribute("data-status", "ready");
    await expect(page.getByRole("button", { name: "Add note" })).toBeDisabled();
    await answered(page, "word250", 30_000);
    await expect(chips(page)).toHaveCount(1);
    await expect(send(page)).toBeEnabled();

    await send(page).click();

    await answered(page, "uploads/next.txt (9 bytes)", 30_000);
    await expect(tray(page)).toHaveCount(0);
  });

  test("a message with files that cannot be sent leaves the files for another try", async ({ page }) => {
    await openChat(page, "Files: a message that is not sent");
    await chosen(page, { name: "kept.txt", content: "keep me" });
    await expect(chips(page).first()).toHaveAttribute("data-status", "ready");
    await page.route("**/api/chats/*/messages", (route) =>
      route.fulfill({ status: 500, json: { error: { code: "internal", message: "The message was lost" } } }),
    );

    await send(page).click();

    await expect(page.getByRole("alert").filter({ hasText: "The message was lost" })).toBeVisible();
    await expect(chips(page)).toHaveCount(1);
    await expect(chips(page).first()).toHaveAttribute("data-status", "ready");
    await expect(send(page)).toBeEnabled();
  });
});

test.describe("attaching files from the home page", () => {
  // Nothing can be sent to a conversation that is not there, so a file waits until the message is sent
  test("a file waits until the message is sent, and then goes to the conversation it starts", async ({ page }) => {
    const requests: string[] = [];
    page.on("request", (request) => {
      if (/\/api\/chats(\/|$)/.test(request.url()) && request.method() !== "GET") requests.push(request.url());
    });

    await chosen(page, { name: "plan.txt", content: "the plan" });

    await expect(chips(page)).toHaveCount(1);
    await expect(chips(page).first()).toHaveAttribute("data-status", "queued");
    await expect(send(page)).toBeEnabled();
    expect(requests).toEqual([]);

    await box(page).fill("Home: what is in the file");
    await send(page).click();
    await page.waitForURL(/\/chat\?id=/);

    await expect(page.getByTestId("user-message")).toContainText("plan.txt");
    await answered(page, "uploads/plan.txt (8 bytes)");
    const id = new URL(page.url()).searchParams.get("id") ?? "";
    expect(await uploaded(page, id)).toContain("uploads/plan.txt");
  });

  test("files dropped while the message is being sent are not taken, since they would miss it", async ({ page }) => {
    await page.route("**/api/chats", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      await new Promise((resolve) => setTimeout(resolve, 1_500));

      return route.continue();
    });
    await chosen(page, { name: "first.txt", content: "first" });
    await box(page).fill("Home: files that come late");
    await send(page).click();
    await expect(send(page)).toBeDisabled();
    const composer = page.locator("form").filter({ has: box(page) });

    const data = await page.evaluateHandle(() => {
      const transfer = new DataTransfer();
      transfer.items.add(new File(["late"], "late.txt", { type: "text/plain" }));

      return transfer;
    });
    await composer.dispatchEvent("dragover", { dataTransfer: data });
    await composer.dispatchEvent("drop", { dataTransfer: data });
    await page.waitForTimeout(300);

    await expect(chips(page)).toHaveCount(1);
    await expect(chips(page).first()).toContainText("first.txt");
    await page.waitForURL(/\/chat\?id=/);
    await expect(page.getByTestId("user-message")).toContainText("first.txt");
    await expect(page.getByTestId("user-message")).not.toContainText("late.txt");
  });

  test("a message may be a file alone, and the conversation is called after it", async ({ page }) => {
    await chosen(page, { name: "alone.txt", content: "just me" });

    await send(page).click();
    await page.waitForURL(/\/chat\?id=/);

    await expect(page.getByTestId("chat-title")).toHaveText("alone.txt");
    await answered(page, "uploads/alone.txt (7 bytes)");
  });

  test("a file that is too large is turned away before there is a conversation", async ({ page }) => {
    await chosen(page, { name: "huge.bin", content: Buffer.alloc(LIMIT + 1) });

    await expect(page.getByRole("alert").filter({ hasText: "huge.bin is larger than the 20 KB that can be attached" })).toBeVisible();
    await expect(tray(page)).toHaveCount(0);
    await expect(send(page)).toBeDisabled();
  });

  test("a file that cannot be sent leaves no conversation behind, and is tried again when it is asked to be", async ({ page }) => {
    const before = ((await (await page.request.get("/api/chats")).json()).chats as unknown[]).length;
    // The files go together, so which is asked first is not known: it is the one that is named that fails, once
    let failed = false;
    await page.route("**/uploads?*", (route) => {
      if (failed || !route.request().url().includes("retry-me.txt")) return route.continue();
      failed = true;

      return route.fulfill({ status: 500, json: { error: { code: "internal", message: "The disk is full" } } });
    });
    await chosen(page, { name: "retry-me.txt", content: "second time lucky" }, { name: "fine.txt", content: "fine" });
    await box(page).fill("Home: a file that fails once");

    await send(page).click();

    await expect(page.getByRole("alert").filter({ hasText: "The disk is full" })).toBeVisible();
    await expect(page).toHaveURL(/\/$|\/\?/);
    await expect(page.getByRole("heading", { name: HOME_HEADING })).toBeVisible();
    const after = ((await (await page.request.get("/api/chats")).json()).chats as unknown[]).length;
    expect(after).toBe(before);
    await expect(chips(page).filter({ hasText: "retry-me.txt" })).toHaveAttribute("data-status", "failed");
    // The file that was taken by a conversation that is gone is to be sent again, to the next
    await expect(chips(page).filter({ hasText: "fine.txt" })).toHaveAttribute("data-status", "queued");
    await expect(send(page)).toBeDisabled();

    await page.getByRole("button", { name: "Retry retry-me.txt" }).click();
    await expect(chips(page).filter({ hasText: "retry-me.txt" })).toHaveAttribute("data-status", "queued");
    await send(page).click();
    await page.waitForURL(/\/chat\?id=/);

    await answered(page, "uploads/retry-me.txt");
    await expect(page.getByTestId("lead-message")).toContainText("uploads/fine.txt");
  });
});
