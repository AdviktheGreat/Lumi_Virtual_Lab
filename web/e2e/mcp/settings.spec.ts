import type { Locator, Page } from "@playwright/test";
import { expect, test } from "../fixtures";
import { openSettings } from "../own-server/state";
import { forget, program, servers, setUp } from "./state";

// The servers whose tools the lead can be given are the server's, which these tests change. The tests of the chat run
// beside these, so each of them names the servers its conversation is given, and what is looked at here is the row of a
// server and not the list of all of them.
test.describe.configure({ mode: "serial" });

const MINE = "mine";
const PRESETS = ["paperclip", "adaptyv", "adaptyv_testing", "proto", "proto_hosted"];

test.afterEach(async ({ page }) => {
  for (const name of [MINE, "missing", "keyed", ...PRESETS]) await forget(page, name);
  expect((await page.request.delete("/api/keys/PAPERCLIP_API_KEY")).ok()).toBe(true);
});

const row = (dialog: Locator, name: string) => dialog.getByTestId(`mcp-${name}`);
const box = (dialog: Locator, name: string, title: string) => row(dialog, name).getByRole("checkbox", { name: title, exact: true });

async function openTools(page: Page): Promise<Locator> {
  const dialog = await openSettings(page, "Tools");
  await expect(dialog.getByRole("heading", { name: "MCP servers" })).toBeVisible();
  await expect(dialog.getByRole("list", { name: "MCP servers" })).toBeVisible();

  return dialog;
}

async function describeOf(page: Page, name: string) {
  const found = (await servers(page)).find((server) => server.name === name);
  expect(found, `${name} is listed`).toBeDefined();

  return found as NonNullable<typeof found> & { keys_set: string[]; missing: { name: string; settable: boolean }[]; auth: string | null };
}

test.describe("the servers of the library", () => {
  test("are listed with what each is for, none on to begin with, and which ask before a call or are signed in to", async ({ page }) => {
    const dialog = await openTools(page);

    for (const [name, title, about] of [
      ["paperclip", "Paperclip", "Search and read papers, trials, patents, and regulatory documents"],
      ["adaptyv", "Adaptyv Foundry", "Have proteins made and tested in a lab, which costs money"],
      ["adaptyv_testing", "Adaptyv Foundry testing sandbox", "Try Adaptyv's calls out where nothing is ordered or charged"],
      ["proto", "Proto, run here", "Run tools for protein and sequence design on your own Modal account"],
      ["proto_hosted", "Proto, hosted", "The same tools with nothing installed here, signed in to with a Proto account"],
    ]) {
      await expect(row(dialog, name)).toContainText(about);
      await expect(box(dialog, name, title)).not.toBeChecked();
    }
    await expect(row(dialog, "paperclip").getByText("Asks before a call")).toHaveCount(0);
    for (const name of ["adaptyv", "adaptyv_testing", "proto", "proto_hosted"]) {
      await expect(row(dialog, name).getByText("Asks before a call")).toBeVisible();
    }
    await expect(row(dialog, "proto_hosted").getByText("Signs in", { exact: true })).toBeVisible();
    await expect(row(dialog, "paperclip").getByText("Signs in", { exact: true })).toHaveCount(0);
    await expect(row(dialog, "proto").getByText("Runs a program on this computer")).toBeVisible();
    await expect(row(dialog, "paperclip").getByText("Reached over HTTP")).toBeVisible();
    // The library's servers are not removed, only turned on or off
    await expect(dialog.getByRole("button", { name: /^Remove (paperclip|proto)/ })).toHaveCount(0);
  });

  test("are turned on at once, and off, with the page showing it as it is chosen, and are kept", async ({ page }) => {
    const dialog = await openTools(page);
    const count = dialog.getByTestId("mcp-count");

    const on = page.waitForRequest((request) => request.method() === "PATCH" && request.url().endsWith("/api/mcp/servers/paperclip"));
    await box(dialog, "paperclip", "Paperclip").click();

    expect((await on).postDataJSON()).toEqual({ enabled: true });
    await expect(box(dialog, "paperclip", "Paperclip")).toBeChecked();
    await expect(count).toHaveText(/^\d+ of \d+ are on$|^All \d+ are on$/);
    await expect.poll(async () => (await describeOf(page, "paperclip")).enabled).toBe(true);

    await page.reload();
    const again = await openTools(page);
    await expect(box(again, "paperclip", "Paperclip")).toBeChecked();

    await box(again, "paperclip", "Paperclip").click();
    await expect(box(again, "paperclip", "Paperclip")).not.toBeChecked();
    await expect.poll(async () => (await describeOf(page, "paperclip")).enabled).toBe(false);
  });

  test("that need a key take it, say it is set without ever showing it, and forget it when told to", async ({ page }) => {
    const secret = "gxl_the-key-of-a-test";
    const dialog = await openTools(page);
    await box(dialog, "paperclip", "Paperclip").click();
    const key = row(dialog, "paperclip").getByLabel("Paperclip key", { exact: true });

    await expect(key).toHaveAttribute("type", "password");
    await expect(row(dialog, "paperclip").getByTestId("key-state-PAPERCLIP_API_KEY")).toHaveText("Not set");
    expect((await describeOf(page, "paperclip")).missing).toEqual([{ name: "PAPERCLIP_API_KEY", settable: true }]);

    await key.fill(secret);
    await row(dialog, "paperclip").getByRole("button", { name: "Save" }).click();

    await expect(row(dialog, "paperclip").getByTestId("key-state-PAPERCLIP_API_KEY")).toHaveText("Set");
    await expect(key).toHaveValue("");
    const kept = await describeOf(page, "paperclip");
    expect(kept.missing).toEqual([]);
    expect(kept.keys_set).toEqual(["PAPERCLIP_API_KEY"]);
    expect(await (await page.request.get("/api/mcp")).text()).not.toContain(secret);
    expect(await (await page.request.get("/api/keys")).text()).not.toContain(secret);

    await row(dialog, "paperclip").getByRole("button", { name: "Remove the Paperclip key" }).click();

    await expect(row(dialog, "paperclip").getByTestId("key-state-PAPERCLIP_API_KEY")).toHaveText("Not set");
    expect((await describeOf(page, "paperclip")).missing).toEqual([{ name: "PAPERCLIP_API_KEY", settable: true }]);
  });

  test("that can be signed in to are chosen between a key and the researcher's account", async ({ page }) => {
    const dialog = await openTools(page);
    await box(dialog, "paperclip", "Paperclip").click();
    const account = row(dialog, "paperclip").getByRole("radio", { name: "Your account, signed in to in the browser" });
    const key = row(dialog, "paperclip").getByRole("radio", { name: "An API key" });
    await expect(key).toBeChecked();
    await expect(row(dialog, "paperclip").getByLabel("Paperclip key", { exact: true })).toBeVisible();

    const sent = page.waitForRequest((request) => request.method() === "PATCH" && request.url().endsWith("/api/mcp/servers/paperclip") && request.postData()?.includes("auth") === true);
    await account.click();

    expect((await sent).postDataJSON()).toEqual({ auth: "oauth" });
    await expect(account).toBeChecked();
    await expect(row(dialog, "paperclip").getByText("Signs in", { exact: true })).toBeVisible();
    await expect(row(dialog, "paperclip").getByLabel("Paperclip key", { exact: true })).toHaveCount(0);
    expect((await describeOf(page, "paperclip")).auth).toBe("oauth");

    await key.click();

    await expect(key).toBeChecked();
    await expect(row(dialog, "paperclip").getByText("Signs in", { exact: true })).toHaveCount(0);
    await expect(row(dialog, "paperclip").getByLabel("Paperclip key", { exact: true })).toBeVisible();
    expect((await describeOf(page, "paperclip")).auth).toBe("key");
  });

  test("say how to set one up, where that is not a key to paste", async ({ page }) => {
    const dialog = await openTools(page);

    const setup = row(dialog, "proto").locator("details");
    await expect(setup).not.toHaveAttribute("open", "");
    await setup.getByText("How to set it up").click();

    await expect(setup).toContainText("proto-tools-mcp");
    await expect(setup).toContainText("modal token new");
  });
});

test.describe("a server of one's own", () => {
  const add = async (dialog: Locator, name: string, entry: string) => {
    await dialog.getByLabel("Name", { exact: true }).fill(name);
    await dialog.getByLabel("How to reach it").fill(entry);
    await dialog.getByRole("button", { name: "Add the server" }).click();
  };

  test("is added by what a config of any other tool would say of it, and is on, and is kept", async ({ page }) => {
    const dialog = await openTools(page);
    await expect(dialog.getByText("A server that starts a program runs it on this computer", { exact: false })).toBeVisible();

    await add(dialog, MINE, JSON.stringify(program()));

    await expect(dialog.getByText(`Saved ${MINE}. It is on, so conversations begun from now on are given its tools.`)).toBeVisible();
    await expect(box(dialog, MINE, MINE)).toBeChecked();
    await expect(row(dialog, MINE)).toContainText("Runs a program on this computer");
    await expect(dialog.getByLabel("Name", { exact: true })).toHaveValue("");
    await expect(dialog.getByLabel("How to reach it")).toHaveValue("");
    expect(await describeOf(page, MINE)).toMatchObject({ added: true, enabled: true, preset: false, problem: null });

    await page.reload();
    const again = await openTools(page);
    await expect(box(again, MINE, MINE)).toBeChecked();
  });

  test("is not added while its name or what describes it is wrong, and says what is wrong where", async ({ page }) => {
    const dialog = await openTools(page);
    const name = dialog.getByLabel("Name", { exact: true });
    const entry = dialog.getByLabel("How to reach it");
    const submit = dialog.getByRole("button", { name: "Add the server" });

    await submit.click();
    await expect(dialog.getByText("Give the server a name.")).toBeVisible();
    await expect(name).toBeFocused();
    await expect(name).toHaveAttribute("aria-invalid", "true");

    await name.fill("1st");
    await submit.click();
    await expect(dialog.getByText("A name starts with a letter and is made of letters, digits, and _, at most 32.")).toBeVisible();

    await name.fill("paperclip");
    await submit.click();
    await expect(dialog.getByText("paperclip is the name of one of the library's servers: name yours something else.")).toBeVisible();

    await name.fill(MINE);
    await expect(dialog.getByText("paperclip is the name of one of the library's servers", { exact: false })).toHaveCount(0);
    await submit.click();
    await expect(dialog.getByText("Describe the server in JSON", { exact: false })).toBeVisible();
    await expect(entry).toBeFocused();

    await entry.fill("{");
    await submit.click();
    await expect(dialog.getByText("That is not JSON:", { exact: false })).toBeVisible();

    await entry.fill("[]");
    await submit.click();
    await expect(dialog.getByText("A server is described by an object", { exact: false })).toBeVisible();

    // What the page cannot tell is told by the server, in its words
    await entry.fill(JSON.stringify({ url: "https://example.com/mcp", colour: "red" }));
    await submit.click();
    await expect(dialog.getByRole("alert").filter({ hasText: "settings that are not used: colour" })).toBeVisible();

    expect((await servers(page)).some((server) => server.name === MINE)).toBe(false);
  });

  test("is turned off, which is kept, and a conversation begun after that is not given it", async ({ page }) => {
    await setUp(page, MINE, program());
    await page.reload();
    const dialog = await openTools(page);
    const given = async () => (await (await page.request.post("/api/chats", { data: { title: "MCP settings: what is given" } })).json()).config.mcp as string[];
    expect(await given()).toContain(MINE);

    const off = page.waitForRequest((request) => request.method() === "PATCH" && request.url().endsWith(`/api/mcp/servers/${MINE}`));
    await box(dialog, MINE, MINE).click();

    expect((await off).postDataJSON()).toEqual({ enabled: false });
    await expect(box(dialog, MINE, MINE)).not.toBeChecked();
    await expect.poll(async () => (await describeOf(page, MINE)).enabled).toBe(false);
    expect(await given()).not.toContain(MINE);

    await page.reload();
    await expect(box(await openTools(page), MINE, MINE)).not.toBeChecked();
  });

  test("is shown as it is chosen while the server has yet to answer, and says why when it refuses", async ({ page }) => {
    await setUp(page, MINE, program());
    await page.reload();
    const dialog = await openTools(page);
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/api/mcp/servers/*", async (route) => {
      if (route.request().method() === "PATCH") await held;
      await route.continue();
    });

    await box(dialog, MINE, MINE).click();

    await expect(box(dialog, MINE, MINE)).not.toBeChecked();
    expect((await describeOf(page, MINE)).enabled).toBe(true);
    release();
    await expect.poll(async () => (await describeOf(page, MINE)).enabled).toBe(false);
    await page.unroute("**/api/mcp/servers/*");

    await page.route("**/api/mcp/servers/*", (route) =>
      route.request().method() === "PATCH"
        ? route.fulfill({
            status: 422,
            contentType: "application/json",
            body: JSON.stringify({ error: { code: "invalid", message: "That server cannot be turned on" } }),
          })
        : route.continue(),
    );
    await box(dialog, MINE, MINE).click();

    await expect(dialog.getByRole("alert").filter({ hasText: "That server cannot be turned on" })).toBeVisible();
    await expect(box(dialog, MINE, MINE)).not.toBeChecked();
    await page.unroute("**/api/mcp/servers/*");
  });

  test("is removed once the researcher says so, and is not removed when they keep it", async ({ page }) => {
    await setUp(page, MINE, program());
    await page.reload();
    const dialog = await openTools(page);

    await dialog.getByRole("button", { name: `Remove ${MINE}` }).click();
    const question = page.getByRole("alertdialog", { name: `Remove ${MINE}?` });
    await expect(question).toContainText("Conversations that have begun keep the tools they were given.");
    await question.getByRole("button", { name: "Keep" }).click();

    await expect(row(dialog, MINE)).toBeVisible();
    expect((await servers(page)).some((server) => server.name === MINE)).toBe(true);
    await expect(dialog.getByRole("button", { name: `Remove ${MINE}` })).toBeFocused();

    await dialog.getByRole("button", { name: `Remove ${MINE}` }).click();
    await page.getByRole("alertdialog", { name: `Remove ${MINE}?` }).getByRole("button", { name: "Remove", exact: true }).click();

    await expect(row(dialog, MINE)).toHaveCount(0);
    await expect(dialog.getByText(`Removed ${MINE}.`)).toBeVisible();
    // Nothing is left to be pressed where the button was, so the focus is where the next server is added
    await expect(dialog.getByLabel("Name", { exact: true })).toBeFocused();
    expect((await servers(page)).some((server) => server.name === MINE)).toBe(false);
  });

  test("says why it cannot work, when the program it starts is not there", async ({ page }) => {
    await setUp(page, "missing", { command: ["no-such-program-of-a-test"] });
    await page.reload();
    const dialog = await openTools(page);

    await expect(row(dialog, "missing").getByRole("alert")).toHaveText(
      "The program no-such-program-of-a-test is not installed here, or is not where the server looks for it.",
    );
  });

  test("says which keys it needs that this page cannot give, and gives no box for them", async ({ page }) => {
    await setUp(page, "keyed", { url: "https://example.com/mcp", headers: { Authorization: "Bearer ${A_KEY_NOBODY_HAS_SET}" } });
    await page.reload();
    const dialog = await openTools(page);

    await expect(row(dialog, "keyed")).toContainText("It needs A_KEY_NOBODY_HAS_SET, which this page cannot give: set it where the server was started, and start it again.");
    await expect(row(dialog, "keyed").getByLabel(/key$/)).toHaveCount(0);
  });
});
