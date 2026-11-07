import type { Page } from "@playwright/test";
import { accessibilityProblems, pastTheEdge } from "../axe";
import { expect, test } from "../fixtures";
import { resetTools } from "./state";

// The search of the web is one of the library's tools, and not a server, so that it is turned on and off with the others, and is
// given the key of Exa that makes it search with that engine. Both are the server's own, which these tests change, so each puts
// them back and none is run beside another. What is of the servers of the page is tried beside it, on the server of the MCP
// tests (see e2e/mcp/tools-nexus.spec.ts).
test.describe.configure({ mode: "serial" });

const EXA = "EXA_API_KEY";

async function reset(page: Page): Promise<void> {
  await resetTools(page);
  expect((await page.request.delete(`/api/keys/${EXA}`)).ok()).toBe(true);
}

test.beforeEach(async ({ page }) => {
  await reset(page);
  await page.goto("/tools");
  await expect(card(page)).toBeVisible();
  await expect(card(page).getByTestId("web-search-engine")).toBeVisible();
});

test.afterEach(async ({ page }) => {
  await reset(page);
});

const card = (page: Page) => page.getByTestId("tool-web_search");
const switchOf = (page: Page) => card(page).getByRole("switch", { name: "Give new programs Web search" });
const engine = (page: Page) => card(page).getByTestId("web-search-engine");

async function webTools(page: Page): Promise<{ name: string; enabled: boolean }[]> {
  const { tools } = await (await page.request.get("/api/tools")).json();

  return tools.filter((tool: { group: string }) => tool.group === "Web");
}

test.describe("the web search among the tools", () => {
  test("is reached from the rail, which shows where it is", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Tools" }).click();

    await expect(page).toHaveURL(/\/tools$/);
    await expect(page.getByRole("heading", { name: "Tools Nexus", level: 1 })).toBeVisible();
    await expect(page).toHaveTitle("Tools Nexus · Lumi Virtual Lab");
    await expect(page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Tools" })).toHaveAttribute("aria-current", "page");
  });

  test("is on to begin with, ready as it is, and searches with the engine that needs no key", async ({ page }) => {
    await expect(card(page)).toContainText("Search the web and read the pages it finds");
    await expect(card(page)).toContainText("Needs: Nothing. A key for Exa is optional");
    await expect(card(page).getByTestId("tool-status")).toHaveText("Ready");
    await expect(switchOf(page)).toHaveAttribute("aria-checked", "true");
    await expect(engine(page)).toHaveText("DuckDuckGo");
    await expect(card(page)).toContainText("turns away a client that searches often");
    expect((await webTools(page)).length).toBeGreaterThan(0);
  });

  test("is turned off for every tool of the web at once, kept, and turned on again", async ({ page }) => {
    const names = (await webTools(page)).map((tool) => tool.name);

    const off = page.waitForRequest((request) => request.method() === "PUT" && request.url().endsWith("/api/tools"));
    await switchOf(page).click();

    expect((await off).postDataJSON()).toEqual({ disabled: names });
    await expect(switchOf(page)).toHaveAttribute("aria-checked", "false");
    await expect.poll(async () => (await webTools(page)).every((tool) => !tool.enabled)).toBe(true);
    const { tools } = await (await page.request.get("/api/tools")).json();
    expect(tools.filter((tool: { enabled: boolean }) => !tool.enabled)).toHaveLength(names.length);

    await page.reload();
    await expect(switchOf(page)).toHaveAttribute("aria-checked", "false");

    await switchOf(page).click();

    await expect(switchOf(page)).toHaveAttribute("aria-checked", "true");
    await expect.poll(async () => (await webTools(page)).every((tool) => tool.enabled)).toBe(true);
  });

  test("is given a key of Exa, which is never shown, and searches with Exa until the key is taken away", async ({ page }) => {
    const secret = "exa_the-key-of-a-test";
    await card(page).getByRole("button", { name: /^Manage/ }).click();
    const setup = page.getByTestId("tool-web_search-setup");
    const key = setup.getByLabel("Exa key", { exact: true });

    await expect(key).toHaveAttribute("type", "password");
    await expect(setup.getByTestId(`key-state-${EXA}`)).toHaveText("Not set");

    await key.fill(secret);
    await setup.getByRole("button", { name: "Save" }).click();

    await expect(setup.getByTestId(`key-state-${EXA}`)).toHaveText("Set");
    await expect(setup.getByText("Saved in the Test Keychain.", { exact: true })).toBeVisible();
    await expect(engine(page)).toHaveText("Exa");
    await expect(card(page)).toContainText("Searches with Exa, for which a key is set.");
    await expect(key).toHaveValue("");
    expect(await (await page.request.get("/api/keys")).text()).not.toContain(secret);
    await page.reload();
    await expect(engine(page)).toHaveText("Exa");

    await card(page).getByRole("button", { name: /^Manage/ }).click();
    await page.getByTestId("tool-web_search-setup").getByRole("button", { name: "Remove the Exa key" }).click();

    await expect(engine(page)).toHaveText("DuckDuckGo");
  });

  test("tells a failure to keep what was chosen, and shows the switch as the server holds it", async ({ page }) => {
    await page.route("**/api/tools", (route) =>
      route.request().method() === "PUT"
        ? route.fulfill({ status: 500, json: { error: { code: "internal", message: "The tools could not be kept" } } })
        : route.continue(),
    );

    await switchOf(page).click();

    await expect(card(page).getByRole("alert")).toContainText("The tools could not be kept");
    await expect(switchOf(page)).toHaveAttribute("aria-checked", "true");
  });

  test("has nothing a keyboard or a screen reader cannot use, and does not need the page scrolled sideways on a narrow screen", async ({ page }) => {
    await card(page).getByRole("button", { name: /^Manage/ }).click();
    await expect(page.getByTestId("tool-web_search-setup")).toBeVisible();

    expect(await accessibilityProblems(page)).toEqual([]);

    await page.setViewportSize({ width: 375, height: 800 });
    expect(await pastTheEdge(page)).toBeLessThanOrEqual(0);
  });
});
