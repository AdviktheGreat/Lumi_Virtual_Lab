import type { Page } from "@playwright/test";
import { accessibilityProblems, pastTheEdge } from "../axe";
import { expect, test } from "../fixtures";
import { forget, program, servers, setUp } from "./state";

// The servers a person gives the lab are the server's, which these tests change, so each puts back what it added. The tests of
// the settings and of the chat run beside these on the same server, and change the library's servers (Paperclip, Proto), so what
// is tried here with a server is tried with servers of its own, named for this page, and the library's are only looked at, in
// what no other test changes: what each is for and what it takes. The catalog's servers are third parties', so adding one
// is only kept and shown, and no test asks it for anything (its entry has been checked against the real server by hand, and by
// the tests of the catalog in tests/test_server_mcp_catalog.py).
test.describe.configure({ mode: "serial" });

const OWN = ["nexus_prog", "nexus_keyed", "nexus_missing", "nexus_new"];
const FROM_THE_CATALOG = ["context7", "synapse", "deepwiki"];

test.afterEach(async ({ page }) => {
  for (const name of [...OWN, ...FROM_THE_CATALOG]) await forget(page, name);
});

const card = (page: Page, name: string) => page.getByTestId(`tool-${name}`);
const listed = (page: Page, name: string) => page.getByTestId(`catalog-${name}`);
const status = (page: Page, name: string) => card(page, name).getByTestId("tool-status");
const switchOf = (page: Page, name: string, title: string) => card(page, name).getByRole("switch", { name: `Give new programs ${title}` });
const setupOf = (page: Page, name: string) => page.getByTestId(`tool-${name}-setup`);
const opener = (page: Page, name: string, title: string) => card(page, name).getByRole("button", { name: new RegExp(`^(Set up|Manage) ${title}$`) });
const said = (page: Page) => page.getByTestId("tools-said");
const dialog = (page: Page) => page.getByRole("dialog", { name: "Add an MCP server" });
const biology = (page: Page) => page.getByRole("list", { name: "Biology", exact: true });

async function open(page: Page, catalog = true): Promise<void> {
  await page.goto("/tools");
  await expect(page.getByRole("heading", { name: "Tools Nexus", level: 1 })).toBeVisible();
  await expect(card(page, "paperclip")).toBeVisible();
  if (catalog) await expect(biology(page)).toBeVisible();
}

test.describe("the tools of the lab", () => {
  test("are shown as cards that say what each is for and what it takes, without those that are not ready to be used", async ({ page }) => {
    await open(page);

    await expect(page.getByRole("list", { name: "Your tools" })).toBeVisible();
    for (const name of ["web_search", "paperclip", "proto", "proto_hosted"]) await expect(card(page, name)).toBeVisible();
    await expect(card(page, "paperclip")).toContainText("Search and read papers, trials, patents, and regulatory documents");
    await expect(card(page, "paperclip")).toContainText("Reached over HTTP");
    await expect(card(page, "paperclip")).toContainText("Needs: An API key, or your account signed in to in the browser");
    await expect(card(page, "proto")).toContainText("Needs: A program installed on this computer");
    await expect(card(page, "proto").getByText("Asks before a call")).toBeVisible();
    await expect(card(page, "proto_hosted")).toContainText("Needs: Your account, signed in to in the browser");
    await expect(card(page, "proto_hosted").getByText("Signs in", { exact: true })).toBeVisible();
    // Adaptyv is not offered until it is ready to be used from here
    await expect(card(page, "adaptyv")).toHaveCount(0);
    await expect(card(page, "adaptyv_testing")).toHaveCount(0);
    await expect(page.locator("main")).not.toContainText("Adaptyv");
    // Each has its own switch, which says what it is for
    for (const [name, title] of [["paperclip", "Paperclip"], ["proto", "Proto, run here"], ["proto_hosted", "Proto, hosted"]]) {
      await expect(switchOf(page, name, title)).toBeVisible();
    }
  });

  test("say that a server that needs a key it cannot be given here is not ready, and what to do", async ({ page }) => {
    await setUp(page, "nexus_keyed", { url: "http://127.0.0.1:9/mcp", headers: { Authorization: "Bearer ${NEXUS_TEST_KEY}" } });
    await open(page);

    await expect(status(page, "nexus_keyed")).toHaveText("Needs setup");
    await expect(card(page, "nexus_keyed")).toContainText("Needs: A key set where the server was started");
    await opener(page, "nexus_keyed", "nexus_keyed").click();
    await expect(setupOf(page, "nexus_keyed")).toContainText("NEXUS_TEST_KEY");
    await expect(setupOf(page, "nexus_keyed")).toContainText("which this page cannot give");
    await expect(setupOf(page, "nexus_keyed").getByRole("button", { name: /^Check connection/ })).toHaveCount(0);
  });

  test("say that a program that is not installed is a problem", async ({ page }) => {
    await setUp(page, "nexus_missing", { command: ["/no/such/program-for-nexus"] });
    await open(page);

    await expect(status(page, "nexus_missing")).toHaveText("Problem");
    await opener(page, "nexus_missing", "nexus_missing").click();
    await expect(setupOf(page, "nexus_missing").getByRole("alert")).toBeVisible();
  });

  test("open to where a library server is set up, with the key asked for, which is never shown, and close again", async ({ page }) => {
    await open(page);
    const button = opener(page, "paperclip", "Paperclip");

    await expect(button).toHaveAttribute("aria-expanded", "false");
    await button.click();

    await expect(button).toHaveAttribute("aria-expanded", "true");
    await expect(setupOf(page, "paperclip").getByLabel("Paperclip key", { exact: true })).toHaveAttribute("type", "password");
    await expect(setupOf(page, "paperclip").getByRole("radio", { name: "An API key" })).toBeVisible();
    await expect(setupOf(page, "paperclip").getByRole("radio", { name: "Your account, signed in to in the browser" })).toBeVisible();

    await button.click();

    await expect(setupOf(page, "paperclip")).toHaveCount(0);
    await expect(button).toHaveAttribute("aria-expanded", "false");
  });

  test("are turned on and off from the card, and kept", async ({ page }) => {
    await setUp(page, "nexus_prog", program());
    await open(page);
    const on = switchOf(page, "nexus_prog", "nexus_prog");
    await expect(on).toHaveAttribute("aria-checked", "true");
    await expect(status(page, "nexus_prog")).toHaveText("Ready");

    const off = page.waitForRequest((request) => request.method() === "PATCH" && request.url().endsWith("/api/mcp/servers/nexus_prog"));
    await on.click();

    expect((await off).postDataJSON()).toEqual({ enabled: false });
    await expect(on).toHaveAttribute("aria-checked", "false");
    await expect.poll(async () => (await servers(page)).find((server) => server.name === "nexus_prog")?.enabled).toBe(false);
    await page.reload();
    await expect(switchOf(page, "nexus_prog", "nexus_prog")).toHaveAttribute("aria-checked", "false");

    await switchOf(page, "nexus_prog", "nexus_prog").click();

    await expect(switchOf(page, "nexus_prog", "nexus_prog")).toHaveAttribute("aria-checked", "true");
    await expect.poll(async () => (await servers(page)).find((server) => server.name === "nexus_prog")?.enabled).toBe(true);
  });

  test("are connected to from the card, which names the tools the lead would be given", async ({ page }) => {
    await setUp(page, "nexus_prog", program());
    await open(page);

    await opener(page, "nexus_prog", "nexus_prog").click();
    await setupOf(page, "nexus_prog").getByRole("button", { name: "Check connection to nexus_prog" }).click();

    const found = setupOf(page, "nexus_prog").getByRole("status").filter({ hasText: "Connected." });
    await expect(found).toContainText(/Connected\. It gives \d+ tools:/);
    await expect(found.locator("code", { hasText: /^nexus_prog_lookup$/ })).toBeVisible();
  });
});

test.describe("the catalog of more tools", () => {
  test("is shown by what its servers are for, with who runs each, what it needs, and where it is reached", async ({ page }) => {
    await open(page);

    await expect(biology(page).getByRole("listitem")).toHaveCount(8);
    await expect(page.getByRole("list", { name: "Software and models", exact: true }).getByRole("listitem")).toHaveCount(3);
    await expect(listed(page, "context7")).toContainText("Upstash");
    await expect(listed(page, "context7")).toContainText("Needs: Nothing");
    await expect(listed(page, "context7")).toContainText("Reached at mcp.context7.com");
    await expect(listed(page, "synapse")).toContainText("Needs: Your account, signed in to in the browser");
    await expect(listed(page, "synapse").getByText("Asks before a call")).toBeVisible();
    await expect(listed(page, "synapse").getByText("Signs in", { exact: true })).toBeVisible();
    await expect(listed(page, "open_targets").getByText("Signs in", { exact: true })).toHaveCount(0);
    // What each is, is read before it is added, at its own site, which opens in another tab and is not followed from here
    const about = listed(page, "context7").getByRole("link", { name: "About Context7" });
    await expect(about).toHaveAttribute("href", /^https:\/\//);
    await expect(about).toHaveAttribute("target", "_blank");
    await expect(about).toHaveAttribute("rel", /noopener/);
    await expect(page.getByTestId("catalog-empty")).toHaveCount(0);
  });

  test("gives a server that is added on at once, which moves to the tools of the lab, and is kept", async ({ page }) => {
    await open(page);
    const request = page.waitForRequest((sent) => sent.method() === "POST" && sent.url().endsWith("/api/mcp/catalog/context7"));

    await listed(page, "context7").getByRole("button", { name: "Add Context7" }).click();

    await request;
    await expect(listed(page, "context7")).toHaveCount(0);
    await expect(card(page, "context7")).toBeVisible();
    await expect(card(page, "context7")).toContainText("Context7");
    await expect(switchOf(page, "context7", "Context7")).toHaveAttribute("aria-checked", "true");
    await expect(said(page)).toHaveText("Added Context7. It is on, so programs begun from now on are given its tools.");
    // The focus goes to the card that is there now, since the one it was on is gone
    await expect(card(page, "context7").getByRole("button").first()).toBeFocused();
    const kept = (await servers(page)).find((server) => server.name === "context7");
    expect(kept?.enabled).toBe(true);
    expect(kept?.preset).toBe(false);
    await expect(card(page, "context7")).toContainText("mcp.context7.com/mcp");

    await page.reload();
    await expect(card(page, "context7")).toBeVisible();
    await expect(listed(page, "context7")).toHaveCount(0);
  });

  test("says of a server that is signed in to that the sign-in comes with the first message of a program", async ({ page }) => {
    await open(page);

    await listed(page, "synapse").getByRole("button", { name: "Add Synapse" }).click();

    await expect(said(page)).toContainText("Added Synapse. It is on");
    await expect(said(page)).toContainText("It asks you to sign in when you send the first message of a program that has it.");
    await expect(card(page, "synapse").getByText("Signs in", { exact: true })).toBeVisible();
    await expect(card(page, "synapse").getByText("Asks before a call")).toBeVisible();
    await expect(status(page, "synapse")).toHaveText("Needs sign-in");
  });

  test("tells a server that was added by another page, and shows the lab as it is", async ({ page }) => {
    await open(page);
    await setUp(page, "deepwiki", { url: "https://mcp.deepwiki.com/mcp" });

    await listed(page, "deepwiki").getByRole("button", { name: "Add DeepWiki" }).click();

    await expect(page.getByRole("alert").filter({ hasText: "deepwiki" })).toBeVisible();
    await expect(card(page, "deepwiki")).toBeVisible();
    await expect(listed(page, "deepwiki")).toHaveCount(0);
  });

  test("is not offered a server that is already set up, and offers it again once it is taken away", async ({ page }) => {
    await open(page);
    await listed(page, "context7").getByRole("button", { name: "Add Context7" }).click();
    await expect(card(page, "context7")).toBeVisible();

    await card(page, "context7").getByRole("button", { name: "Remove context7" }).click();
    const question = page.getByRole("alertdialog", { name: "Remove context7?" });
    await question.getByRole("button", { name: "Keep" }).click();

    await expect(question).toHaveCount(0);
    await expect(card(page, "context7")).toBeVisible();
    expect((await servers(page)).some((server) => server.name === "context7")).toBe(true);

    await card(page, "context7").getByRole("button", { name: "Remove context7" }).click();
    await page.getByRole("alertdialog", { name: "Remove context7?" }).getByRole("button", { name: "Remove" }).click();

    await expect(card(page, "context7")).toHaveCount(0);
    await expect(listed(page, "context7")).toBeVisible();
    expect((await servers(page)).some((server) => server.name === "context7")).toBe(false);
    // The button that asked has gone with the server, so the focus is on the one that adds a server
    await expect(page.getByRole("button", { name: "Add MCP server" })).toBeFocused();
  });

  test("keeps a server that is added while a change to another is still being kept", async ({ page }) => {
    await setUp(page, "nexus_prog", program());
    await open(page);
    let release: () => void = () => undefined;
    const hold = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/api/mcp/servers/nexus_prog", async (route) => {
      if (route.request().method() !== "PATCH") return route.continue();
      // The servers as the server gave them before the one was added, which come back after it is
      const answer = await route.fetch();
      await hold;
      await route.fulfill({ response: answer });
    });

    await switchOf(page, "nexus_prog", "nexus_prog").click();
    await expect(switchOf(page, "nexus_prog", "nexus_prog")).toHaveAttribute("aria-checked", "false");
    await listed(page, "context7").getByRole("button", { name: "Add Context7" }).click();

    // The catalog is asked nothing until the change before it has been answered
    await page.waitForTimeout(250);
    expect((await servers(page)).some((server) => server.name === "context7")).toBe(false);
    release();

    await expect(said(page)).toContainText("Added Context7");
    await expect(card(page, "context7")).toBeVisible();
    await expect(switchOf(page, "nexus_prog", "nexus_prog")).toHaveAttribute("aria-checked", "false");
    expect((await servers(page)).some((server) => server.name === "context7")).toBe(true);
  });

  test("is shown to be empty once every server of it is added", async ({ page }) => {
    await page.route("**/api/mcp/catalog", (route) =>
      route.request().method() === "GET"
        ? route.fulfill({
            json: {
              servers: [
                { name: "context7", title: "Context7", about: "Docs", group: "Software and models", maker: "Upstash", site: "https://context7.com", target: "https://mcp.context7.com/mcp", signs_in: false, asks: false, added: true },
              ],
            },
          })
        : route.continue(),
    );
    await open(page, false);

    await expect(page.getByTestId("catalog-empty")).toHaveText("You have added every server of the catalog.");
    await expect(page.getByRole("button", { name: "Add any MCP server" })).toBeVisible();
  });

  test("tells a catalog that could not be read, and reads it again when asked", async ({ page }) => {
    let fail = true;
    await page.route("**/api/mcp/catalog", (route) =>
      route.request().method() === "GET" && fail
        ? route.fulfill({ status: 500, json: { error: { code: "internal", message: "The catalog is not there" } } })
        : route.continue(),
    );
    await page.goto("/tools");

    await expect(page.getByText("The catalog could not be looked at.")).toBeVisible();
    await expect(card(page, "paperclip")).toBeVisible();
    fail = false;
    await page.getByRole("button", { name: "Try again" }).click();

    await expect(biology(page)).toBeVisible();
  });
});

test.describe("a server that is not in the catalog", () => {
  test("is added from the button of the page, or from the catalog, by describing how to reach it", async ({ page }) => {
    await open(page);

    await page.getByRole("button", { name: "Add MCP server" }).click();
    await expect(dialog(page)).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog(page)).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Add MCP server" })).toBeFocused();

    await page.getByRole("button", { name: "Add any MCP server" }).click();
    await expect(dialog(page)).toBeVisible();
    await expect(dialog(page).getByLabel("Name", { exact: true })).toBeFocused();
    await expect(dialog(page)).toContainText("runs it on this computer, with the same access as you");

    await dialog(page).getByLabel("Name", { exact: true }).fill("nexus_new");
    await dialog(page).getByLabel("How to reach it").fill(JSON.stringify(program()));
    await dialog(page).getByRole("button", { name: "Add the server" }).click();

    await expect(dialog(page)).toHaveCount(0);
    await expect(card(page, "nexus_new")).toBeVisible();
    await expect(card(page, "nexus_new")).toContainText("Runs a program on this computer");
    await expect(card(page, "nexus_new").getByRole("button", { name: "Remove nexus_new" })).toBeVisible();
    await expect(said(page)).toHaveText("Saved nexus_new. It is on, so programs begun from now on are given its tools.");
    // The focus is on the card of the server that was added, where the dialog was left
    await expect(card(page, "nexus_new").getByRole("button").first()).toBeFocused();
    const kept = (await servers(page)).find((server) => server.name === "nexus_new");
    expect(kept?.enabled).toBe(true);
    expect(kept?.preset).toBe(false);
  });

  test("is not added by a name that is not allowed, or a description that is not JSON, and says what is wrong", async ({ page }) => {
    await open(page);
    await page.getByRole("button", { name: "Add MCP server" }).click();
    const form = dialog(page);

    await form.getByRole("button", { name: "Add the server" }).click();
    await expect(form.getByText("Give the server a name.")).toBeVisible();
    await expect(form.getByLabel("Name", { exact: true })).toBeFocused();

    await form.getByLabel("Name", { exact: true }).fill("paperclip");
    await form.getByRole("button", { name: "Add the server" }).click();
    await expect(form.getByText("paperclip is the name of one of the library's servers: name yours something else.")).toBeVisible();

    await form.getByLabel("Name", { exact: true }).fill("nexus_new");
    await form.getByLabel("How to reach it").fill("{not json");
    await form.getByRole("button", { name: "Add the server" }).click();
    await expect(form.getByText(/^That is not JSON/)).toBeVisible();
    await expect(form.getByLabel("How to reach it")).toBeFocused();
    expect((await servers(page)).some((server) => server.name === "nexus_new")).toBe(false);
  });

  test("is told of what the server refused, with the form as it was typed", async ({ page }) => {
    await page.route("**/api/mcp/servers/nexus_new", (route) =>
      route.request().method() === "PUT"
        ? route.fulfill({ status: 422, json: { error: { code: "invalid", message: "That is not a server nexus_new can reach" } } })
        : route.continue(),
    );
    await open(page);
    await page.getByRole("button", { name: "Add MCP server" }).click();
    const form = dialog(page);
    await form.getByLabel("Name", { exact: true }).fill("nexus_new");
    await form.getByLabel("How to reach it").fill('{"url": "https://example.com/mcp"}');

    await form.getByRole("button", { name: "Add the server" }).click();

    await expect(form.getByRole("alert")).toHaveText("That is not a server nexus_new can reach");
    await expect(form.getByLabel("Name", { exact: true })).toHaveValue("nexus_new");
    await expect(form.getByLabel("How to reach it")).toHaveValue('{"url": "https://example.com/mcp"}');
    await expect(card(page, "nexus_new")).toHaveCount(0);
  });
});

test.describe("the page", () => {
  test("has nothing a keyboard or a screen reader cannot use, with a card set up, and with the dialog open", async ({ page }) => {
    await setUp(page, "nexus_prog", program());
    await open(page);
    await opener(page, "nexus_prog", "nexus_prog").click();
    await expect(setupOf(page, "nexus_prog")).toBeVisible();

    expect(await accessibilityProblems(page)).toEqual([]);

    await page.getByRole("button", { name: "Add MCP server" }).click();
    await expect(dialog(page)).toBeVisible();
    await expect(dialog(page)).toHaveCSS("opacity", "1");

    expect(await accessibilityProblems(page)).toEqual([]);
  });

  test("does not need to be scrolled sideways on a narrow screen", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await setUp(page, "nexus_prog", program());
    await open(page);

    expect(await pastTheEdge(page)).toBeLessThanOrEqual(0);
  });

  test("is told that the tools could not be looked at, and looks again when asked", async ({ page }) => {
    let fail = true;
    await page.route("**/api/mcp", (route) =>
      route.request().method() === "GET" && fail
        ? route.fulfill({ status: 500, json: { error: { code: "internal", message: "The tools are not there" } } })
        : route.continue(),
    );
    await page.goto("/tools");

    await expect(page.getByText("The tools could not be looked at.")).toBeVisible();
    fail = false;
    await page.getByRole("button", { name: "Try again" }).first().click();

    await expect(card(page, "paperclip")).toBeVisible();
  });
});
