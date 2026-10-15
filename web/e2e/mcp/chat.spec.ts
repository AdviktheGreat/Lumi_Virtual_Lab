import type { Locator, Page } from "@playwright/test";
import { answered, expect, test } from "../fixtures";
import { forget, HttpServer, openChat, program, say, setUp } from "./state";

// The servers are real: the test server of the MCP library's own tests is started as a program for each conversation, as
// a person's would be, and the lead is the script of the server these tests run on. Each test names the servers its
// conversation is given, since the tests of other files run beside these on the one server, and sets up what it needs, since
// they all share the one name that the script calls the tools of.
test.describe.configure({ mode: "serial" });

const calls = (page: Page) => page.getByTestId("call");
const connections = (page: Page) => page.getByTestId("connection");
const approvals = (page: Page) => page.getByTestId("approval");
const questions = (page: Page) => page.getByTestId("question");

async function result(call: Locator): Promise<string> {
  await call.locator("summary").click();

  return (await call.getByText("Result", { exact: true }).locator("xpath=following-sibling::*[1]").textContent()) ?? "";
}

test.afterEach(async ({ page }) => {
  await forget(page, "genes");
});

test.describe("the tools of a server that is on", () => {
  test("are given to the lead once the first message connects to the server, and the server is kept for the next", async ({ page }) => {
    await setUp(page, "genes", program());
    await openChat(page, "MCP: the lead is given the tools", ["genes"]);
    await expect(connections(page)).toHaveCount(0);

    await say(page, "tool:offered");

    await expect(connections(page)).toHaveCount(1);
    await expect(connections(page)).toHaveText(/^Connected to genes, which gave \d+ tools$/);
    await answered(page, "Offered:");
    const offered = page.getByTestId("lead-message").last();
    for (const name of ["genes_echo", "genes_lookup", "genes_total", "pubmed_search"]) {
      await expect(offered).toContainText(new RegExp(`\\b${name}\\b`));
    }

    await say(page, "tool:offered again");
    await expect(page.getByTestId("lead-message")).toHaveCount(2);
    await answered(page, "Offered:");
    await expect(connections(page)).toHaveCount(1);
  });

  test("are called for the lead, and the answer comes back with the call", async ({ page }) => {
    await setUp(page, "genes", program());
    await openChat(page, "MCP: a call that is not asked about", ["genes"]);

    await say(page, "mcp:echo");
    await answered(page, "That is done: 1 step ran.");

    await expect(approvals(page)).toHaveCount(0);
    await expect(calls(page)).toHaveCount(1);
    await expect(calls(page)).toHaveAttribute("data-call", "genes_echo");
    await expect(calls(page)).toContainText("Called genes_echo");
    expect(await result(calls(page))).toBe("ab");
  });

  test("are not given to a conversation that was not told to have them", async ({ page }) => {
    await setUp(page, "genes", program());
    await openChat(page, "MCP: not given", []);

    await say(page, "tool:offered");
    await answered(page, "Offered:");

    await expect(connections(page)).toHaveCount(0);
    await expect(page.getByTestId("lead-message").last()).not.toContainText("genes_echo");
  });

  test("that cannot be reached say so, and are tried again with the next message", async ({ page }) => {
    const later = await HttpServer.chosen();
    try {
      await setUp(page, "genes", program());
      await setUp(page, "later", later.entry);
      await openChat(page, "MCP: a server that is not there", ["genes", "later"]);

      await say(page, "tool:offered");

      await expect(connections(page).filter({ hasText: "genes" })).toHaveAttribute("data-state", "ready");
      const failed = connections(page).filter({ hasText: "later" });
      await expect(failed).toHaveAttribute("data-state", "failed");
      await expect(failed).toContainText("Could not connect to later.");
      await expect(page.getByTestId("chat-state")).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Send", exact: true })).toBeVisible();
      await expect(page.getByTestId("lead-message")).toHaveCount(0);

      await later.start();
      await say(page, "tool:offered");

      await answered(page, "Offered:");
      await expect(connections(page).filter({ hasText: "later" })).toHaveCount(2);
      await expect(connections(page).filter({ hasText: "later" }).last()).toHaveAttribute("data-state", "ready");
      // The one that was there is not connected to again
      await expect(connections(page).filter({ hasText: "genes" })).toHaveCount(1);
      await expect(page.getByTestId("lead-message").last()).toContainText("later_echo");
    } finally {
      later.stop();
      await forget(page, "later");
    }
  });
});

test.describe("a call that waits for the researcher", () => {
  test.beforeEach(async ({ page }) => {
    await setUp(page, "genes", program({ approval: { ask: ["echo", "count"] } }));
  });

  test("is made once it is allowed, and the ones that need no asking are made at once", async ({ page }) => {
    await setUp(page, "genes", program({ approval: { ask: ["echo"] } }));
    await openChat(page, "MCP: a call is allowed", ["genes"]);

    await say(page, "mcp:both");

    const card = approvals(page);
    await expect(card).toHaveAttribute("data-state", "waiting");
    await expect(card).toHaveAccessibleName("Allow genes_echo?");
    await expect(card).toContainText("genes_echo is a tool of genes, and each call to it needs your approval.");
    await expect(card.getByRole("code")).toContainText('"text": "cd"');
    await expect(page.getByTestId("chat-state")).toHaveText("Waiting for you");
    // What does not ask was done before what does
    await expect(calls(page).first()).toHaveAttribute("data-call", "genes_count");
    expect(await result(calls(page).first())).toBe("1");
    await expect(calls(page)).toHaveCount(2);

    await card.getByRole("button", { name: "Allow", exact: true }).click();
    await answered(page, "That is done: 2 steps ran.");

    await expect(approvals(page)).toHaveAttribute("data-state", "approved");
    await expect(approvals(page)).toContainText("Allowed");
    await expect(approvals(page).getByRole("button")).toHaveCount(0);
    expect(await result(calls(page).last())).toBe("cd");
  });

  test("is not made when it is declined, and the lead is told so; asked again, it is made", async ({ page }) => {
    await openChat(page, "MCP: a call is declined", ["genes"]);

    await say(page, "mcp:count");
    // It is called with nothing, which is not shown as something it is called with
    await expect(approvals(page)).toContainText("genes_count is a tool of genes");
    await expect(approvals(page)).not.toContainText("It is to be called with");
    await approvals(page).getByRole("button", { name: "Decline" }).click();
    await answered(page, "That is done: 1 step ran.");

    await expect(approvals(page)).toHaveAttribute("data-state", "declined");
    await expect(approvals(page)).toContainText("Declined");
    expect(await result(calls(page).first())).toContain("declined this call to genes_count, so it was not made");

    await say(page, "mcp:count");
    await approvals(page).last().getByRole("button", { name: "Allow", exact: true }).click();
    await expect(page.getByTestId("lead-message")).toHaveCount(2);
    await answered(page, "That is done: 1 step ran.");

    // Only the second was made, so it is the first the server counted
    expect(await result(calls(page).last())).toBe("1");
  });

  test("is still there when the page is opened again, and is answered from there", async ({ page }) => {
    const id = await openChat(page, "MCP: a call waits while the page is closed", ["genes"]);
    await say(page, "mcp:echo");
    await expect(approvals(page)).toHaveAttribute("data-state", "waiting");

    await page.reload();

    await expect(approvals(page)).toHaveAttribute("data-state", "waiting");
    await expect(page.getByTestId("chat-state")).toHaveText("Waiting for you");
    await approvals(page).getByRole("button", { name: "Allow", exact: true }).click();
    await answered(page, "That is done: 1 step ran.");
    expect(page.url()).toContain(id);
    expect(await result(calls(page))).toBe("ab");
  });

  test("is shown as answered in every window the conversation is open in", async ({ page }) => {
    const id = await openChat(page, "MCP: a call is answered in another window", ["genes"]);
    await say(page, "mcp:echo");
    const other = await page.context().newPage();
    await other.goto(`/chat?id=${id}`);
    await expect(approvals(page)).toHaveAttribute("data-state", "waiting");
    await expect(approvals(other)).toHaveAttribute("data-state", "waiting");

    await approvals(other).getByRole("button", { name: "Decline" }).click();

    await expect(approvals(other)).toHaveAttribute("data-state", "declined");
    await expect(approvals(page)).toHaveAttribute("data-state", "declined");
    await expect(approvals(page).getByRole("button")).toHaveCount(0);
    await answered(page, "That is done: 1 step ran.");
    await other.close();
  });

  test("is not made when the turn is stopped, and the next message is asked about again", async ({ page }) => {
    await openChat(page, "MCP: a call is stopped", ["genes"]);
    await say(page, "mcp:count");
    await expect(approvals(page)).toHaveAttribute("data-state", "waiting");

    await page.getByRole("button", { name: "Stop" }).click();

    await expect(approvals(page)).toHaveAttribute("data-state", "withdrawn");
    await expect(approvals(page)).toContainText("Not answered, so not called");
    await expect(page.getByTestId("chat-state")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Send", exact: true })).toBeVisible();

    await say(page, "mcp:count");
    await expect(approvals(page)).toHaveCount(2);
    await expect(approvals(page).last()).toHaveAttribute("data-state", "waiting");
    await approvals(page).last().getByRole("button", { name: "Allow", exact: true }).click();
    await answered(page, "That is done: 1 step ran.");

    // The call that was stopped was not made, so this is the first the server counted
    expect(await result(calls(page).last())).toBe("1");
  });

  test("is refused by the server once it has been answered, in the server's words", async ({ page }) => {
    const id = await openChat(page, "MCP: a call is answered twice", ["genes"]);
    await say(page, "mcp:echo");
    const sent = page.waitForRequest((request) => request.method() === "POST" && request.url().includes(`/api/chats/${id}/approvals/`));

    await approvals(page).getByRole("button", { name: "Allow", exact: true }).click();
    const first = await sent;
    await answered(page, "That is done: 1 step ran.");

    const again = await page.request.post(first.url(), { data: { allow: false } });
    expect(again.status()).toBe(409);
    expect((await again.json()).error.code).toBe("not_waiting");
    // What was said first stands
    await expect(approvals(page)).toHaveAttribute("data-state", "approved");
  });
});

test.describe("a question a server asks", () => {
  test.beforeEach(async ({ page }) => {
    await setUp(page, "genes", program());
  });

  test("is put as a form, and what is filled in goes back to the tool", async ({ page }) => {
    await openChat(page, "MCP: a form is filled in", ["genes"]);

    await say(page, "mcp:order");

    const card = questions(page);
    await expect(card).toHaveAttribute("data-state", "waiting");
    await expect(card).toHaveAccessibleName("genes asks");
    await expect(card).toContainText("What is to be ordered?");
    await expect(page.getByTestId("chat-state")).toHaveText("Waiting for you");

    await card.getByRole("button", { name: "Send" }).click();
    await expect(card.getByText("Name must be filled in")).toBeVisible();
    await expect(card.getByText("Kind must be filled in")).toBeVisible();

    await card.getByLabel("Name", { exact: true }).fill("guide");
    await card.getByLabel("Kind", { exact: true }).selectOption({ label: "dna" });
    await card.getByLabel("Copies (optional)").fill("2");
    await card.getByRole("button", { name: "Send" }).click();
    await answered(page, "That is done: 1 step ran.");

    await expect(questions(page)).toHaveAttribute("data-state", "answered");
    await expect(questions(page)).toContainText("Answered");
    expect(JSON.parse(await result(calls(page)))).toEqual({ action: "accept", order: { name: "guide", kind: "dna", copies: 2 } });
  });

  test("is declined, which the tool is told", async ({ page }) => {
    await openChat(page, "MCP: a form is declined", ["genes"]);
    await say(page, "mcp:order");

    await questions(page).getByRole("button", { name: "Decline" }).click();
    await answered(page, "That is done: 1 step ran.");

    await expect(questions(page)).toHaveAttribute("data-state", "declined");
    expect(JSON.parse(await result(calls(page)))).toEqual({ action: "decline", order: null });
  });

  test("of yes or no is a box to tick", async ({ page }) => {
    await openChat(page, "MCP: a question of yes or no", ["genes"]);
    await say(page, "mcp:confirm");
    const card = questions(page);

    await expect(card).toContainText("Go ahead with the test?");
    await card.getByRole("checkbox", { name: "Approve" }).check();
    await card.getByRole("button", { name: "Send" }).click();
    await answered(page, "That is done: 1 step ran.");

    expect(await result(calls(page))).toBe("accept True");
  });

  test("is withdrawn when the turn is stopped, and the tool is not answered", async ({ page }) => {
    await openChat(page, "MCP: a question is stopped", ["genes"]);
    await say(page, "mcp:order");
    await expect(questions(page)).toHaveAttribute("data-state", "waiting");

    await page.getByRole("button", { name: "Stop" }).click();

    await expect(questions(page)).toHaveAttribute("data-state", "withdrawn");
    await expect(questions(page)).toContainText("Not answered");
    await expect(questions(page).getByRole("button")).toHaveCount(0);
    await expect(page.getByTestId("chat-state")).toHaveCount(0);
  });
});
