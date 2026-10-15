import type { Page } from "@playwright/test";
import { answered, expect, test } from "../fixtures";
import { forget, HttpServer, openChat, say, setUp } from "./state";

// A server that is signed in to with OAuth is a real one: its authorization server is the test server's own, which signs
// anyone in at once, as a browser would find once a person had signed in. The page shows the link to its sign-in page,
// which the test opens as a person would, in another tab, and which sends the browser back to the server the tests run on.
// No browser is opened by the server, so that nothing is signed in to until the test says so.
test.describe.configure({ mode: "serial" });

// Each is signed in to for the first time by the test that uses it, so that a sign-in kept by another is not found
let vault: HttpServer;
let refused: HttpServer;
let unvisited: HttpServer;

test.beforeAll(async () => {
  [vault, refused, unvisited] = await Promise.all([HttpServer.started("--oauth"), HttpServer.started("--oauth", "--deny"), HttpServer.started("--oauth")]);
});

test.afterAll(() => {
  for (const server of [vault, refused, unvisited]) server.stop();
});

test.afterEach(async ({ page }) => {
  for (const name of ["vault", "refused", "unvisited"]) await forget(page, name);
});

const connection = (page: Page) => page.getByTestId("connection");

test("a server that needs the researcher to sign in waits for them, and goes on once they have", async ({ page }) => {
  await setUp(page, "vault", vault.entry);
  await openChat(page, "MCP: signing in", ["vault"]);

  await say(page, "mcp:signed");

  const card = connection(page);
  await expect(card).toHaveAttribute("data-state", "signing_in");
  await expect(card).toHaveAccessibleName("Sign in to vault");
  await expect(card).toContainText("Waiting for you to sign in");
  await expect(page.getByTestId("chat-state")).toHaveText("Waiting for you");
  const link = card.getByRole("link", { name: "Open the sign-in page" });
  await expect(link).toHaveAttribute("href", new RegExp(`^http://127\\.0\\.0\\.1:${vault.port}/authorize\\?`));
  // Nothing has been signed in to, since nobody has gone to the page
  expect(await vault.stats()).toMatchObject({ signed_in: 0 });

  const opened = page.context().waitForEvent("page");
  await link.click();
  const tab = await opened;
  await expect(tab.getByRole("heading", { name: "Signed in" })).toBeVisible();
  await expect(tab.getByText("You are signed in to vault. You can close this tab.")).toBeVisible();
  await tab.close();

  await expect(card).toHaveAttribute("data-state", "ready");
  await expect(card).toContainText("Connected to vault");
  await answered(page, "That is done: 1 step ran.");
  await expect(page.getByTestId("call")).toHaveAttribute("data-call", "vault_echo");
  expect(await vault.stats()).toMatchObject({ registered: 1, signed_in: 1 });
});

test("is not asked of the researcher again by the next conversation, which finds the sign-in kept", async ({ page }) => {
  await setUp(page, "vault", vault.entry);
  await openChat(page, "MCP: signed in already", ["vault"]);

  await say(page, "mcp:signed");

  await answered(page, "That is done: 1 step ran.");
  await expect(connection(page)).toHaveCount(1);
  await expect(connection(page)).toHaveAttribute("data-state", "ready");
  await expect(page.getByRole("link", { name: "Open the sign-in page" })).toHaveCount(0);
  expect(await vault.stats()).toMatchObject({ registered: 1, signed_in: 1 });
});

test("a sign-in that the researcher turns down at the page fails the connection, and says so", async ({ page }) => {
  await setUp(page, "refused", refused.entry);
  await openChat(page, "MCP: signing in is refused", ["refused"]);

  await say(page, "tool:offered");

  const card = connection(page);
  await expect(card).toHaveAttribute("data-state", "signing_in");
  const opened = page.context().waitForEvent("page");
  await card.getByRole("link", { name: "Open the sign-in page" }).click();
  const tab = await opened;
  await expect(tab.getByRole("heading", { name: "Not signed in" })).toBeVisible();
  await tab.close();

  await expect(card).toHaveAttribute("data-state", "failed");
  await expect(card).toContainText("Could not connect to refused.");
  await expect(card.getByRole("button", { name: "Tool settings" })).toBeVisible();
  await expect(page.getByTestId("chat-state")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Send", exact: true })).toBeVisible();
});

test("a sign-in that is waited for is given up when the turn is stopped", async ({ page }) => {
  await setUp(page, "unvisited", unvisited.entry);
  await openChat(page, "MCP: signing in is stopped", ["unvisited"]);
  await say(page, "tool:offered");
  await expect(connection(page)).toHaveAttribute("data-state", "signing_in");

  await page.getByRole("button", { name: "Stop" }).click();

  await expect(connection(page)).toHaveAttribute("data-state", "failed");
  await expect(page.getByTestId("chat-state")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Open the sign-in page" })).toHaveCount(0);
});
