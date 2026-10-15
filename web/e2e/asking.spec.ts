import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";
import { approval, asked, connection, ended, lead, ORDER_FIELDS, server, tell, user, type Told } from "./replay";

// What the page shows of the servers whose tools the lead is given, and of what they and their tools ask of the researcher.
// The conversation is real and the events it is told of are written here, so that every way a request, a question, or a
// connection can stand is shown; the real servers are in mcp/.

const running: Told = { kind: "status", turn: 0, data: { state: "running" } };
const calling: Told = {
  kind: "tool_calls",
  speaker: lead,
  text: "Echoing it.",
  data: { calls: [{ id: "c1", name: "genes_echo", arguments: JSON.stringify({ text: "ab" }) }] },
};

// Answers what the page sends to the server so that it can be looked at, and says what it sent
async function sentTo(page: Page, path: string, reply: object = { state: "answered" }) {
  const bodies: unknown[] = [];
  await page.route(`**/api/chats/*/${path}`, async (route) => {
    bodies.push(route.request().postDataJSON());
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(reply) });
  });

  return bodies;
}

test.describe("a call that waits for the researcher", () => {
  test("is asked about in the conversation, with what it is to be called with, and is told of as the conversation waits", async ({ page }) => {
    await tell(page, [user("Echo it"), calling, approval("waiting"), running]);

    const card = page.getByTestId("approval");
    await expect(card).toHaveAttribute("data-state", "waiting");
    await expect(card).toHaveAccessibleName("Allow genes_echo?");
    await expect(card).toContainText("genes_echo is a tool of Gene tools, and each call to it needs your approval.");
    await expect(card).toContainText("Says the text back.");
    await expect(card).toContainText("It is to be called with");
    await expect(card.getByRole("code")).toContainText('"text": "ab"');
    await expect(card.getByRole("button", { name: "Allow", exact: true })).toBeEnabled();
    await expect(card.getByRole("button", { name: "Decline" })).toBeEnabled();
    await expect(card.getByRole("status")).toHaveText("Waiting for you to allow or decline genes_echo");
    // The conversation is not at work: it waits for the researcher
    await expect(page.getByTestId("chat-state")).toHaveText("Waiting for you");
    await expect(page.getByText("Thinking…")).toHaveCount(0);
  });

  test("is allowed with one button, which says yes to the server and waits for the conversation to say it was allowed", async ({ page }) => {
    await tell(page, [user("Echo it"), calling, approval("waiting"), running]);
    const sent = await sentTo(page, "approvals/r1", { state: "approved" });

    await page.getByRole("button", { name: "Allow", exact: true }).click();

    await expect.poll(() => sent).toEqual([{ allow: true }]);
    const card = page.getByTestId("approval");
    await expect(card.getByRole("button", { name: "Allow", exact: true })).toBeDisabled();
    await expect(card.getByRole("button", { name: "Decline" })).toBeDisabled();
    await expect(card.getByRole("status", { name: "Sending" })).toBeVisible();
  });

  test("is declined with the other, which says no", async ({ page }) => {
    await tell(page, [user("Echo it"), calling, approval("waiting"), running]);
    const sent = await sentTo(page, "approvals/r1", { state: "declined" });

    await page.getByRole("button", { name: "Decline" }).click();

    await expect.poll(() => sent).toEqual([{ allow: false }]);
  });

  test("is shown as a line once it was answered, or the turn ended before it was, with nothing left to press", async ({ page }) => {
    await tell(page, [
      user("Echo it"),
      calling,
      approval("waiting", "a"),
      approval("approved", "a"),
      approval("waiting", "b"),
      approval("declined", "b"),
      approval("waiting", "c"),
      approval("withdrawn", "c"),
      { kind: "stopped", text: "Stopped." },
    ]);

    const cards = page.getByTestId("approval");
    await expect(cards).toHaveCount(3);
    await expect(cards.nth(0)).toHaveAttribute("data-state", "approved");
    await expect(cards.nth(0)).toContainText("genes_echo");
    await expect(cards.nth(0)).toContainText("Allowed");
    await expect(cards.nth(1)).toHaveAttribute("data-state", "declined");
    await expect(cards.nth(1)).toContainText("Declined");
    await expect(cards.nth(2)).toHaveAttribute("data-state", "withdrawn");
    await expect(cards.nth(2)).toContainText("Not answered, so not called");
    await expect(page.getByRole("button", { name: "Allow", exact: true })).toHaveCount(0);
    await expect(page.getByTestId("chat-state")).toHaveCount(0);
  });

  test("is shown as one that was not answered when the turn ended and the server said nothing of it", async ({ page }) => {
    await tell(page, [user("Echo it"), calling, approval("waiting"), { kind: "stopped", text: "Stopped." }]);

    await expect(page.getByTestId("approval")).toHaveAttribute("data-state", "withdrawn");
    await expect(page.getByRole("button", { name: "Allow", exact: true })).toHaveCount(0);
  });

  test("says why the server refused an answer, and can be answered again", async ({ page }) => {
    await tell(page, [user("Echo it"), calling, approval("waiting"), running]);
    let refuse = true;
    await page.route("**/api/chats/*/approvals/r1", (route) =>
      refuse
        ? route.fulfill({
            status: 409,
            contentType: "application/json",
            body: JSON.stringify({ error: { code: "not_waiting", message: "Nothing waits for an answer under r1" } }),
          })
        : route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ state: "approved" }) }),
    );

    await page.getByRole("button", { name: "Allow", exact: true }).click();

    await expect(page.getByTestId("approval").getByRole("alert")).toHaveText("Nothing waits for an answer under r1");
    await expect(page.getByRole("button", { name: "Allow", exact: true })).toBeEnabled();
    refuse = false;
    await page.getByRole("button", { name: "Allow", exact: true }).click();
    await expect(page.getByTestId("approval").getByRole("alert")).toHaveCount(0);
  });

  test("is refused by the real server when nothing waits for it, in the server's own words", async ({ page }) => {
    await tell(page, [user("Echo it"), calling, approval("waiting"), running]);

    await page.getByRole("button", { name: "Allow", exact: true }).click();

    await expect(page.getByTestId("approval").getByRole("alert")).toContainText("Nothing waits for an answer under r1");
    await expect(page.getByRole("button", { name: "Decline" })).toBeEnabled();
  });
});

test.describe("what a server asks", () => {
  test("is put as a form, with a field for each thing it asks, and the researcher's answers go back by name", async ({ page }) => {
    await tell(page, [user("Order it"), asked({ fields: ORDER_FIELDS, required: ["name", "kind"] }), running]);
    const sent = await sentTo(page, "questions/q1");
    const card = page.getByTestId("question");

    await expect(card).toHaveAccessibleName("Gene tools asks");
    await expect(card).toContainText("What is to be ordered?");
    await expect(card.getByLabel("Sample name")).toBeVisible();
    await expect(card.getByText("What to call it.")).toBeVisible();
    await expect(card.getByLabel("copies (optional)")).toHaveValue("1");
    await expect(card.getByLabel("Kind")).toHaveValue("");
    await expect(card.getByRole("group", { name: "Pick some (optional)" }).getByRole("checkbox")).toHaveCount(3);
    await expect(page.getByTestId("chat-state")).toHaveText("Waiting for you");

    await card.getByLabel("Sample name").fill("guide");
    await card.getByLabel("Kind").selectOption({ label: "dna" });
    await card.getByLabel("copies (optional)").fill("2");
    await card.getByRole("checkbox", { name: "Fresh sample" }).check();
    await card.getByLabel("tags (optional)").fill("x, y");
    await card.getByRole("checkbox", { name: "a", exact: true }).check();
    await card.getByRole("checkbox", { name: "c", exact: true }).check();
    await card.getByRole("button", { name: "Send" }).click();

    await expect
      .poll(() => sent)
      .toEqual([{ answer: { name: "guide", kind: "dna", copies: 2, fresh: true, tags: ["x", "y"], picks: ["a", "c"] } }]);
  });

  test("is not answered while what must be filled in is not, or is not what the field takes, and says what is wrong where", async ({ page }) => {
    await tell(page, [user("Order it"), asked({ fields: ORDER_FIELDS, required: ["name", "kind"] }), running]);
    const sent = await sentTo(page, "questions/q1");
    const card = page.getByTestId("question");

    await card.getByLabel("copies (optional)").fill("two");
    await card.getByRole("button", { name: "Send" }).click();

    await expect(card.getByText("Sample name must be filled in")).toBeVisible();
    await expect(card.getByText("Kind must be filled in")).toBeVisible();
    await expect(card.getByText("copies is a whole number")).toBeVisible();
    await expect(card.getByLabel("Sample name")).toBeFocused();
    await expect(card.getByLabel("Sample name")).toHaveAttribute("aria-invalid", "true");
    expect(sent).toEqual([]);

    await card.getByLabel("Sample name").fill("guide");
    await expect(card.getByText("Sample name must be filled in")).toHaveCount(0);
    await card.getByLabel("Kind").selectOption({ label: "protein" });
    await card.getByLabel("copies (optional)").fill("3");
    await card.getByRole("button", { name: "Send" }).click();

    await expect.poll(() => sent).toEqual([{ answer: { name: "guide", kind: "protein", copies: 3, fresh: false } }]);
  });

  test("is declined with a button, which sends no answer", async ({ page }) => {
    await tell(page, [user("Order it"), asked({ fields: ORDER_FIELDS, required: ["name", "kind"] }), running]);
    const sent = await sentTo(page, "questions/q1", { state: "declined" });

    await page.getByTestId("question").getByRole("button", { name: "Decline" }).click();

    await expect.poll(() => sent).toEqual([{ answer: null }]);
  });

  test("of yes or no is a box to tick, which says no when it is not", async ({ page }) => {
    await tell(page, [user("Confirm it"), asked({ fields: { approve: { type: "boolean", title: "Go ahead" } }, required: ["approve"], text: "Go ahead with the test?" }), running]);
    const sent = await sentTo(page, "questions/q1");
    const card = page.getByTestId("question");

    await expect(card.getByRole("checkbox", { name: "Go ahead" })).not.toBeChecked();
    await card.getByRole("button", { name: "Send" }).click();
    await expect.poll(() => sent).toEqual([{ answer: { approve: false } }]);

    // Once it is sent the card waits for the conversation to say it was answered, so it is shown again
    await page.reload();
    await card.getByRole("checkbox", { name: "Go ahead" }).check();
    await card.getByRole("button", { name: "Send" }).click();
    await expect.poll(() => sent).toEqual([{ answer: { approve: false } }, { answer: { approve: true } }]);
  });

  test("with nothing to fill in is agreed to, with a button of its own", async ({ page }) => {
    await tell(page, [user("Agree"), asked({ text: "Do you agree?" }), running]);
    const sent = await sentTo(page, "questions/q1");
    const card = page.getByTestId("question");

    await expect(card.getByRole("textbox")).toHaveCount(0);
    await expect(card.getByRole("button", { name: "Send" })).toHaveCount(0);
    await card.getByRole("button", { name: "Agree" }).click();

    await expect.poll(() => sent).toEqual([{ answer: {} }]);
  });

  test("that is answered at a web page is a link to it that opens elsewhere, and is answered once it was done", async ({ page }) => {
    await tell(page, [user("Pay"), asked({ url: "https://pay.example.org/test", text: "Pay for the test at this page." }), running]);
    const sent = await sentTo(page, "questions/q1");
    const card = page.getByTestId("question");

    const link = card.getByRole("link", { name: "https://pay.example.org/test" });
    await expect(link).toHaveAttribute("href", "https://pay.example.org/test");
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
    await expect(card.getByRole("textbox")).toHaveCount(0);

    await card.getByRole("button", { name: "I have done it" }).click();

    await expect.poll(() => sent).toEqual([{ answer: {} }]);
  });

  test("that asks for a page that is not on the web is not made a link, and can only be declined", async ({ page }) => {
    await tell(page, [user("Pay"), asked({ url: "javascript:window.__pwned=true", text: "Go here." }), running]);
    const sent = await sentTo(page, "questions/q1", { state: "declined" });
    const card = page.getByTestId("question");

    await expect(card.getByRole("link")).toHaveCount(0);
    await expect(card.getByRole("alert")).toContainText("not a web address");
    await expect(card.getByRole("button", { name: "I have done it" })).toBeDisabled();
    await card.getByRole("button", { name: "Decline" }).click();

    await expect.poll(() => sent).toEqual([{ answer: null }]);
    expect(await page.evaluate(() => (window as unknown as { __pwned?: boolean }).__pwned)).toBeUndefined();
  });

  test("is shown as a line once it was answered, declined, or the turn ended before it was", async ({ page }) => {
    await tell(page, [
      user("Order it"),
      asked({ fields: { n: { type: "integer" } }, required: ["n"], request: "a" }),
      ended("answered", "a"),
      asked({ request: "b" }),
      ended("declined", "b"),
      asked({ request: "c" }),
      { kind: "stopped", text: "Stopped." },
    ]);

    const cards = page.getByTestId("question");
    await expect(cards).toHaveCount(3);
    await expect(cards.nth(0)).toHaveAttribute("data-state", "answered");
    await expect(cards.nth(0)).toContainText("Gene tools asked");
    await expect(cards.nth(0)).toContainText("What is to be ordered?");
    await expect(cards.nth(0)).toContainText("Answered");
    await expect(cards.nth(1)).toHaveAttribute("data-state", "declined");
    await expect(cards.nth(1)).toContainText("Declined");
    await expect(cards.nth(2)).toHaveAttribute("data-state", "withdrawn");
    await expect(cards.nth(2)).toContainText("Not answered");
    await expect(cards.getByRole("button")).toHaveCount(0);
  });

  test("that was declined without being asked says what it asked and why", async ({ page }) => {
    await tell(page, [
      user("Pay"),
      {
        kind: "question",
        text: "Go there.\n\nIt was declined without asking, since it points to 'file:///etc', which is not a web address.",
        data: { request: "z", state: "declined", ...server },
      },
    ]);

    const card = page.getByTestId("question");
    await expect(card).toHaveAttribute("data-state", "declined");
    await expect(card).toContainText("Go there.");
    await expect(page.getByRole("button", { name: "Decline" })).toHaveCount(0);
  });

  test("with a choice that need not be made shows the choices by their titles, and can leave it out", async ({ page }) => {
    await tell(page, [
      user("Order it"),
      asked({ fields: { kind: { type: "string", oneOf: [{ const: "p", title: "Protein" }, { const: "d", title: "DNA" }], title: "Kind" } } }),
      running,
    ]);
    const sent = await sentTo(page, "questions/q1");
    const card = page.getByTestId("question");

    await expect(card.getByLabel("Kind (optional)")).toHaveValue("");
    await expect(card.getByRole("option", { name: "Leave it out" })).toBeAttached();
    await card.getByRole("button", { name: "Send" }).click();
    await expect.poll(() => sent).toEqual([{ answer: {} }]);

    await page.reload();
    await card.getByLabel("Kind (optional)").selectOption({ label: "DNA" });
    await card.getByRole("button", { name: "Send" }).click();
    await expect.poll(() => sent).toEqual([{ answer: {} }, { answer: { kind: "d" } }]);
  });
});

test.describe("a server being connected to", () => {
  test("is said to be, then said to be connected to, with how many tools it gave", async ({ page }) => {
    await tell(page, [user("Go"), connection("connecting"), connection("ready", { tools: 1 }), connection("connecting", { server: "geo", title: "Gene expression" }), connection("ready", { server: "geo", title: "Gene expression", tools: 12 })]);

    const rows = page.getByTestId("connection");
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(0)).toHaveText("Connected to Gene tools, which gave 1 tool");
    await expect(rows.nth(1)).toHaveText("Connected to Gene expression, which gave 12 tools");
  });

  test("is said to be, while it is, and the lead is not said to be thinking", async ({ page }) => {
    await tell(page, [user("Go"), connection("connecting"), running]);

    await expect(page.getByTestId("connection")).toHaveText("Connecting to Gene tools");
    await expect(page.getByTestId("connection")).toHaveAttribute("data-state", "connecting");
    await expect(page.getByText("Thinking…")).toHaveCount(0);
  });

  test("that needs the researcher to sign in is a link to the page, which is opened elsewhere", async ({ page }) => {
    await tell(page, [user("Go"), connection("connecting"), connection("signing_in", { url: "https://sign.example.org/authorize?x=1" }), running]);

    const card = page.getByTestId("connection");
    await expect(card).toHaveAccessibleName("Sign in to Gene tools");
    const link = card.getByRole("link", { name: "Open the sign-in page" });
    await expect(link).toHaveAttribute("href", "https://sign.example.org/authorize?x=1");
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
    await expect(card).toContainText("Waiting for you to sign in");
    await expect(page.getByTestId("chat-state")).toHaveText("Waiting for you");
    await expect(page.getByText("Thinking…")).toHaveCount(0);
  });

  test("with a sign-in page that is not on the web is not made a link", async ({ page }) => {
    await tell(page, [user("Go"), connection("connecting"), connection("signing_in", { url: "javascript:window.__pwned=true" }), running]);

    const card = page.getByTestId("connection");
    await expect(card.getByRole("link")).toHaveCount(0);
    await expect(card.getByRole("alert")).toContainText("not a web address");
  });

  test("that could not be connected to says why, and where to put it right", async ({ page }) => {
    await tell(page, [
      user("Go"),
      connection("connecting"),
      connection("failed", {}, "The server did not answer within 30 seconds."),
      { kind: "failed", text: "No tools were given." },
    ]);

    const card = page.getByTestId("connection");
    await expect(card).toHaveAttribute("data-state", "failed");
    await expect(card).toContainText("Could not connect to Gene tools.");
    await expect(card).toContainText("The server did not answer within 30 seconds.");

    await card.getByRole("button", { name: "Tool settings" }).click();
    const dialog = page.getByRole("dialog", { name: "Settings" });
    await expect(dialog.getByRole("tab", { name: "Tools" })).toHaveAttribute("aria-selected", "true");
    await expect(dialog.getByRole("heading", { name: "MCP servers" })).toBeVisible();
  });

  test("that was being connected to when the turn ended is said not to have been", async ({ page }) => {
    await tell(page, [user("Go"), connection("connecting"), { kind: "stopped", text: "Stopped." }]);

    const card = page.getByTestId("connection");
    await expect(card).toHaveAttribute("data-state", "failed");
    await expect(card).toContainText("Not connected: the turn ended before it was.");
  });
});
