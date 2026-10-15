import type { Locator, Page } from "@playwright/test";
import { answered, expect, test } from "../fixtures";
import { openSettings } from "../own-server/state";
import { forget, HttpServer, openChat, program, say, setUp } from "./state";

// Looking at a server from the settings is a real connection: to the test server started as a program, to one reached over
// HTTP that is there or is not, and to one that is signed in to with OAuth, whose authorization server is the test server's
// own. The sign-in is made in a conversation, as a person makes it, and the tests that follow it find it kept.
test.describe.configure({ mode: "serial" });

let gate: HttpServer;

test.beforeAll(async () => {
  gate = await HttpServer.started("--oauth");
});

test.afterAll(() => gate.stop());

test.afterEach(async ({ page }) => {
  for (const name of ["checked", "away", "gate", "adaptyv_testing"]) await forget(page, name);
  expect((await page.request.delete("/api/keys/FOUNDRY_TESTING_TOKEN")).ok()).toBe(true);
});

const row = (dialog: Locator, name: string) => dialog.getByTestId(`mcp-${name}`);
const check = (dialog: Locator, name: string) => row(dialog, name).getByRole("button", { name: `Check connection to ${name}` });

async function openTools(page: Page): Promise<Locator> {
  const dialog = await openSettings(page, "Tools");
  await expect(dialog.getByRole("list", { name: "MCP servers" })).toBeVisible();

  return dialog;
}

test.describe("a server that is a program", () => {
  test("is connected to, and the tools it gives are named as the lead is given them", async ({ page }) => {
    await setUp(page, "checked", program());
    const dialog = await openTools(page);

    await check(dialog, "checked").click();

    const found = row(dialog, "checked").getByRole("status").filter({ hasText: "Connected." });
    await expect(found).toContainText(/Connected\. It gives \d+ tools:/);
    // Named as the lead is given them, after the server, and only as many as fit are named
    await expect(found.locator("code", { hasText: /^checked_lookup$/ })).toBeVisible();
    await expect(found.locator("code", { hasText: /^checked_echo$/ })).toBeVisible();
    await expect(found).toContainText(/ and \d+ more$/);
    await expect(row(dialog, "checked").getByRole("alert")).toHaveCount(0);
  });

  test("is checked whether or not it is on, and stays as it was", async ({ page }) => {
    await setUp(page, "checked", program({ enabled: false }));
    const dialog = await openTools(page);
    const box = row(dialog, "checked").getByRole("checkbox", { name: "checked", exact: true });
    await expect(box).not.toBeChecked();

    await check(dialog, "checked").click();

    await expect(row(dialog, "checked").getByRole("status").filter({ hasText: "Connected." })).toBeVisible();
    await expect(box).not.toBeChecked();
  });

  test("says it is connecting while it waits, and is not asked again then", async ({ page }) => {
    await setUp(page, "checked", program());
    const dialog = await openTools(page);
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => (release = resolve));
    let asked = 0;
    await page.route("**/api/mcp/servers/checked/check", async (route) => {
      asked += 1;
      await held;
      await route.continue();
    });

    await check(dialog, "checked").click();

    await expect(row(dialog, "checked").getByRole("status").filter({ hasText: "Connecting…" })).toBeVisible();
    await expect(check(dialog, "checked")).toBeDisabled();
    release();
    await expect(row(dialog, "checked").getByRole("status").filter({ hasText: "Connected." })).toBeVisible();
    await expect(check(dialog, "checked")).toBeEnabled();
    expect(asked).toBe(1);
  });

  test("a new check takes the finding of the last away while it goes on, and shows the new one", async ({ page }) => {
    await setUp(page, "checked", program());
    const dialog = await openTools(page);
    await check(dialog, "checked").click();
    await expect(row(dialog, "checked").getByRole("status").filter({ hasText: "Connected." })).toBeVisible();
    await page.route("**/api/mcp/servers/checked/check", (route) =>
      route.fulfill({ json: { ok: false, tools: [], reason: "It stopped answering." } }),
    );

    await check(dialog, "checked").click();

    await expect(row(dialog, "checked").getByRole("alert")).toHaveText("It stopped answering.");
    await expect(row(dialog, "checked").getByText("Connected.")).toHaveCount(0);
  });

  test("is said to give many tools by naming some of them and how many more", async ({ page }) => {
    await setUp(page, "checked", program());
    const dialog = await openTools(page);
    const tools = Array.from({ length: 15 }, (_, at) => `checked_tool_${at}`);
    await page.route("**/api/mcp/servers/checked/check", (route) => route.fulfill({ json: { ok: true, tools, reason: null } }));

    await check(dialog, "checked").click();

    const found = row(dialog, "checked").getByRole("status").filter({ hasText: "Connected." });
    await expect(found).toContainText("Connected. It gives 15 tools:");
    await expect(found.locator("code")).toHaveCount(12);
    await expect(found).toContainText("and 3 more");
  });
});

test.describe("a server that cannot be checked", () => {
  test("says why it could not be connected to", async ({ page }) => {
    const away = await HttpServer.chosen();
    await setUp(page, "away", away.entry);
    const dialog = await openTools(page);

    await check(dialog, "away").click();

    await expect(row(dialog, "away").getByRole("alert")).toContainText("Could not connect to the MCP server away");
    await expect(row(dialog, "away").getByText("Connected.")).toHaveCount(0);
    await expect(check(dialog, "away")).toBeEnabled();
  });

  test("says what the server answered when it would not check", async ({ page }) => {
    await setUp(page, "checked", program());
    const dialog = await openTools(page);
    await page.route("**/api/mcp/servers/checked/check", (route) =>
      route.fulfill({ status: 409, json: { error: { code: "busy", message: "checked is being checked" } } }),
    );

    await check(dialog, "checked").click();

    await expect(row(dialog, "checked").getByRole("alert")).toHaveText("checked is being checked");
    await expect(check(dialog, "checked")).toBeEnabled();
  });

  test("is not told of what a check found once the key or how it is signed in to is changed", async ({ page }) => {
    const dialog = await openTools(page);
    const sandbox = row(dialog, "adaptyv_testing");
    const look = sandbox.getByRole("button", { name: "Check connection to Adaptyv Foundry testing sandbox" });
    const found = sandbox.getByRole("status").filter({ hasText: "Connected." });
    await page.route("**/api/mcp/servers/adaptyv_testing/check", (route) =>
      route.fulfill({ json: { ok: true, tools: ["adaptyv_testing_targets"], reason: null } }),
    );
    const typed = sandbox.getByRole("textbox", { name: "Adaptyv Foundry testing sandbox key" });
    const keyed = async (value: string) => {
      await typed.fill(value);
      await sandbox.getByRole("button", { name: "Save" }).click();
      await expect(sandbox.getByTestId("key-state-FOUNDRY_TESTING_TOKEN")).toHaveText("Set");
      await expect(typed).toHaveValue("");
    };
    await keyed("first-key");
    await look.click();
    await expect(found).toBeVisible();

    await keyed("second-key");

    await expect(found).toHaveCount(0);
    await look.click();
    await expect(found).toBeVisible();

    await sandbox.getByRole("radio", { name: "Your account, signed in to in the browser" }).click();

    await expect(found).toHaveCount(0);
    await expect(sandbox.getByTestId("mcp-adaptyv_testing-sign-in")).toContainText("Not signed in yet.");
    await look.click();
    await expect(found).toBeVisible();

    await sandbox.getByRole("radio", { name: "An API key" }).click();

    await expect(found).toHaveCount(0);
  });

  test("is not told of what a check found that was still going when the key was changed", async ({ page }) => {
    const dialog = await openTools(page);
    const sandbox = row(dialog, "adaptyv_testing");
    let release: () => void = () => undefined;
    const hold = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/api/mcp/servers/adaptyv_testing/check", async (route) => {
      await hold;
      await route.fulfill({ json: { ok: true, tools: ["adaptyv_testing_targets"], reason: null } });
    });
    const typed = sandbox.getByRole("textbox", { name: "Adaptyv Foundry testing sandbox key" });
    await typed.fill("first-key");
    await sandbox.getByRole("button", { name: "Save" }).click();
    await sandbox.getByRole("button", { name: "Check connection to Adaptyv Foundry testing sandbox" }).click();
    await expect(sandbox.getByRole("status").filter({ hasText: "Connecting…" })).toBeVisible();

    await typed.fill("second-key");
    await sandbox.getByRole("button", { name: "Save" }).click();
    await expect(sandbox.getByRole("status").filter({ hasText: "Connecting…" })).toHaveCount(0);
    const over = page.waitForResponse("**/api/mcp/servers/adaptyv_testing/check");
    release();
    await over;

    // The page has had the time to show it, if it were going to
    await page.waitForTimeout(250);
    await expect(sandbox.getByText("Connected.")).toHaveCount(0);
    await expect(sandbox.getByRole("button", { name: "Check connection to Adaptyv Foundry testing sandbox" })).toBeEnabled();
  });

  test("is not told of what the server answered to a check that was still going when the key was changed", async ({
    page,
  }) => {
    const dialog = await openTools(page);
    const sandbox = row(dialog, "adaptyv_testing");
    let release: () => void = () => undefined;
    const hold = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/api/mcp/servers/adaptyv_testing/check", async (route) => {
      await hold;
      await route.fulfill({ status: 409, json: { error: { code: "busy", message: "The sandbox is being checked" } } });
    });
    const typed = sandbox.getByRole("textbox", { name: "Adaptyv Foundry testing sandbox key" });
    await typed.fill("first-key");
    await sandbox.getByRole("button", { name: "Save" }).click();
    await sandbox.getByRole("button", { name: "Check connection to Adaptyv Foundry testing sandbox" }).click();
    await expect(sandbox.getByRole("status").filter({ hasText: "Connecting…" })).toBeVisible();

    await typed.fill("second-key");
    await sandbox.getByRole("button", { name: "Save" }).click();
    await expect(sandbox.getByRole("status").filter({ hasText: "Connecting…" })).toHaveCount(0);
    const over = page.waitForResponse("**/api/mcp/servers/adaptyv_testing/check");
    release();
    await over;

    await page.waitForTimeout(250);
    await expect(sandbox.getByText("The sandbox is being checked")).toHaveCount(0);
    await expect(sandbox.getByRole("alert")).toHaveCount(0);
  });

  test("is not offered a check while a key it needs is missing", async ({ page }) => {
    const dialog = await openTools(page);

    await expect(row(dialog, "adaptyv_testing").getByRole("button", { name: /^Check connection/ })).toHaveCount(0);
    await expect(row(dialog, "adaptyv_testing")).toContainText("FOUNDRY_TESTING_TOKEN");
    // One that needs none is
    await expect(row(dialog, "proto_hosted").getByRole("button", { name: "Check connection to Proto, hosted" })).toBeVisible();
  });
});

test.describe("a server that is signed in to", () => {
  const signIn = (dialog: Locator) => dialog.getByTestId("mcp-gate-sign-in");

  test("says it is not signed in yet, and a check says so without sending anyone to a sign-in page", async ({ page }) => {
    await setUp(page, "gate", gate.entry);
    const dialog = await openTools(page);

    await expect(signIn(dialog)).toContainText("Not signed in yet.");
    await expect(row(dialog, "gate").getByRole("button", { name: "Sign out of gate" })).toHaveCount(0);
    await check(dialog, "gate").click();

    await expect(row(dialog, "gate").getByRole("alert")).toContainText("gate is not signed in to yet");
    expect(await gate.stats()).toMatchObject({ signed_in: 0 });
  });

  test("is signed in to in a conversation, and the settings then say so", async ({ page }) => {
    await setUp(page, "gate", gate.entry);
    await openChat(page, "MCP: signing in to the gate", ["gate"]);
    await say(page, "mcp:gated");
    const card = page.getByTestId("connection");
    await expect(card).toHaveAttribute("data-state", "signing_in");
    const opened = page.context().waitForEvent("page");
    await card.getByRole("link", { name: "Open the sign-in page" }).click();
    const tab = await opened;
    await expect(tab.getByRole("heading", { name: "Signed in" })).toBeVisible();
    await tab.close();
    await answered(page, "That is done: 1 step ran.");

    const dialog = await openTools(page);

    await expect(signIn(dialog)).toHaveText("Signed in. Conversations use it without asking you.");
    await expect(row(dialog, "gate").getByRole("button", { name: "Sign out of gate" })).toBeVisible();
  });

  test("is connected to with the sign-in that is kept, and nobody is sent anywhere", async ({ page }) => {
    await setUp(page, "gate", gate.entry);
    const dialog = await openTools(page);

    await check(dialog, "gate").click();

    const found = row(dialog, "gate").getByRole("status").filter({ hasText: "Connected." });
    await expect(found.locator("code", { hasText: /^gate_authorization$/ })).toBeVisible();
    expect(await gate.stats()).toMatchObject({ registered: 1, signed_in: 1 });
  });

  test("is signed out of, which a check then finds, and the next conversation is asked to sign in again", async ({ page }) => {
    await setUp(page, "gate", gate.entry);
    const dialog = await openTools(page);
    await check(dialog, "gate").click();
    await expect(row(dialog, "gate").getByRole("status").filter({ hasText: "Connected." })).toBeVisible();

    await row(dialog, "gate").getByRole("button", { name: "Sign out of gate" }).click();

    await expect(dialog.getByRole("status").filter({ hasText: "Signed out of gate." })).toBeVisible();
    await expect(signIn(dialog)).toContainText("Not signed in yet.");
    await expect(row(dialog, "gate").getByRole("button", { name: "Sign out of gate" })).toHaveCount(0);
    // What the check found was of the server signed in to
    await expect(row(dialog, "gate").getByText("Connected.")).toHaveCount(0);
    await check(dialog, "gate").click();
    await expect(row(dialog, "gate").getByRole("alert")).toContainText("gate is not signed in to yet");

    await page.keyboard.press("Escape");
    await openChat(page, "MCP: signing in again", ["gate"]);
    await say(page, "mcp:gated");
    await expect(page.getByTestId("connection")).toHaveAttribute("data-state", "signing_in");
    expect(await gate.stats()).toMatchObject({ signed_in: 1 });
  });

  test("is not told it is signed in to for a server that is not", async ({ page }) => {
    await setUp(page, "checked", program());
    const dialog = await openTools(page);

    await expect(row(dialog, "checked").getByText(/Signed in|Not signed in yet/)).toHaveCount(0);
    await expect(row(dialog, "checked").getByRole("button", { name: /^Sign out/ })).toHaveCount(0);
  });
});
