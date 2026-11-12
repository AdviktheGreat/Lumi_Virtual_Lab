import type { Locator, Page } from "@playwright/test";
import { accessibilityProblems, pastTheEdge } from "../axe";
import { expect, test } from "../fixtures";
import { openSettings } from "../own-server/state";
import { contextProgram, forget, HttpServer, look, openChat, program, setUp } from "./state";

// What a server lists besides its tools is real: the test server of the MCP library's own tests is started with its resources and
// prompts, connected to by a check, and what it listed is kept and shown. Its prompts are written after a slash, which the server
// writes out into the box, and is never sent until the person sends it. Each test puts back the servers it set up.
test.describe.configure({ mode: "serial" });

test.afterEach(async ({ page }) => {
  for (const name of ["held", "heldaway"]) await forget(page, name);
});

const card = (page: Page, name: string) => page.getByTestId(`tool-${name}`);
const setupOf = (page: Page, name: string) => page.getByTestId(`tool-${name}-setup`);
const lists = (page: Page, name: string) => card(page, name).getByTestId(`tool-${name}-lists`);
const holdsOf = (scope: Page | Locator, name: string) => scope.getByTestId(`mcp-${name}-holds`);
const opener = (page: Page, name: string) => card(page, name).getByRole("button", { name: new RegExp(`^(Set up|Manage) ${name}$`) });
const box = (page: Page) => page.getByRole("textbox", { name: "Message" });
const menu = (page: Page) => page.getByTestId("slash-menu");
const options = (page: Page) => menu(page).getByTestId("slash-option");

async function openTools(page: Page): Promise<void> {
  await page.goto("/tools");
  await expect(page.getByRole("heading", { name: "Tools Nexus", level: 1 })).toBeVisible();
  await expect(card(page, "paperclip")).toBeVisible();
}

// What the menu lists, by the names the lines are given
async function listed(page: Page): Promise<(string | null)[]> {
  return options(page).evaluateAll((lines) => lines.map((line) => line.getAttribute("data-command")));
}

// The page where a program is begun, once it has read the servers, which a command written at once is not taken for a message before
async function openHome(page: Page): Promise<void> {
  const read = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/mcp" && response.request().method() === "GET");
  await page.goto("/");
  await expect(box(page)).toBeVisible();
  await read;
}

test.describe("what a server lists besides its tools", () => {
  test("is shown on the card and in where it is set up once the server has been checked", async ({ page }) => {
    await setUp(page, "held", contextProgram());
    await openTools(page);
    await expect(lists(page, "held")).toHaveCount(0);
    await opener(page, "held").click();
    await expect(holdsOf(setupOf(page, "held"), "held")).toHaveCount(0);

    await setupOf(page, "held").getByRole("button", { name: "Check connection to held" }).click();

    await expect(setupOf(page, "held").getByRole("status").filter({ hasText: "Connected." })).toBeVisible();
    const holds = holdsOf(setupOf(page, "held"), "held");
    await expect(holds.locator("summary")).toHaveText("It also lists 3 resources and 2 prompts");
    await expect(lists(page, "held")).toHaveText("Also lists: 3 resources and 2 prompts");

    await holds.locator("summary").click();
    const resources = holds.getByTestId("mcp-resource");
    await expect(resources).toHaveCount(3);
    await expect(resources.filter({ hasText: "panel" })).toContainText("genes://panel");
    await expect(resources.filter({ hasText: "panel" })).toContainText("The genes of the test panel");
    await expect(resources.filter({ hasText: "gene-card" })).toContainText("Template");
    await expect(resources.filter({ hasText: "gene-card" })).toContainText("genes://gene/{symbol}");
    const prompts = holds.getByTestId("mcp-prompt");
    await expect(prompts).toHaveCount(2);
    await expect(prompts.filter({ hasText: "/held_summarize_gene" })).toContainText("symbol");
    await expect(prompts.filter({ hasText: "/held_summarize_gene" })).toContainText("depth (optional)");
    await expect(prompts.filter({ hasText: "/held_summarize_gene" })).toContainText("Summarize what is known of a gene");
    await expect(prompts.filter({ hasText: "/held_compare_genes" })).not.toContainText("optional");
    await expect(holds).toContainText("Seen just now.");
    expect(await accessibilityProblems(page)).toEqual([]);
    expect(await pastTheEdge(page)).toBeLessThanOrEqual(0);
  });

  test("is kept, and shown again when the page is opened, with when it was seen and without another look", async ({ page }) => {
    await setUp(page, "held", contextProgram());
    await look(page, "held");

    await openTools(page);

    await expect(lists(page, "held")).toHaveText("Also lists: 3 resources and 2 prompts");
    await opener(page, "held").click();
    const holds = holdsOf(setupOf(page, "held"), "held");
    await expect(holds.locator("summary")).toHaveText("It also lists 3 resources and 2 prompts");
    await holds.locator("summary").click();
    await expect(holds).toContainText(/Seen (just now|\d+ min ago)\./);
    await expect(setupOf(page, "held").getByRole("status").filter({ hasText: "Connected." })).toHaveCount(0);
  });

  test("is shown while the server is off, and is not shown for one that was changed since, until it is checked again", async ({ page }) => {
    await setUp(page, "held", contextProgram({ enabled: false }));
    await look(page, "held");
    await openTools(page);
    await expect(lists(page, "held")).toHaveText("Also lists: 3 resources and 2 prompts");

    // Set up in another way, so that what it listed was of the server as it was
    await setUp(page, "held", contextProgram({ enabled: false, env: { HELD_CHANGED: "yes" } }));
    await page.reload();

    await expect(card(page, "held")).toBeVisible();
    await expect(lists(page, "held")).toHaveCount(0);
    await opener(page, "held").click();
    await expect(holdsOf(setupOf(page, "held"), "held")).toHaveCount(0);
    await setupOf(page, "held").getByRole("button", { name: "Check connection to held" }).click();
    await expect(lists(page, "held")).toHaveText("Also lists: 3 resources and 2 prompts");
  });

  test("is said to be nothing for a server that lists none", async ({ page }) => {
    await setUp(page, "held", program());
    await openTools(page);
    await opener(page, "held").click();

    await setupOf(page, "held").getByRole("button", { name: "Check connection to held" }).click();

    await expect(holdsOf(setupOf(page, "held"), "held")).toHaveText("It lists no resources or prompts. Seen just now.");
    await expect(lists(page, "held")).toHaveCount(0);
  });

  test("is shown in the settings as it is on the Tools page", async ({ page }) => {
    await setUp(page, "held", contextProgram());
    await page.goto("/");
    const dialog = await openSettings(page, "Tools");
    const row = dialog.getByTestId("mcp-held");

    await row.getByRole("button", { name: "Check connection to held" }).click();

    const holds = holdsOf(row, "held");
    await expect(holds.locator("summary")).toHaveText("It also lists 3 resources and 2 prompts");
    await holds.locator("summary").click();
    await expect(holds.getByTestId("mcp-prompt")).toHaveCount(2);
  });
});

test.describe("the prompts of a server in the menu of commands", () => {
  test("are listed at the page where a program is begun for the letters of their commands, with the server each is of", async ({ page }) => {
    await setUp(page, "held", contextProgram());
    await look(page, "held");
    await openHome(page);

    await box(page).fill("/held");
    await expect.poll(() => listed(page)).toEqual(["/held_summarize_gene", "/held_compare_genes"]);
    await expect(options(page).first()).toContainText("Prompt of held: Summarize what is known of a gene");
    expect(await accessibilityProblems(page)).toEqual([]);
    expect(await pastTheEdge(page)).toBeLessThanOrEqual(0);

    // Not for a slash alone, and Tab writes the command out, which then waits for what it needs
    await box(page).fill("/");
    await expect(menu(page)).toBeVisible();
    expect(await listed(page)).not.toContain("/held_summarize_gene");
    await box(page).fill("/held_comp");
    await expect.poll(() => listed(page)).toEqual(["/held_compare_genes"]);
    await box(page).press("Tab");
    await expect(box(page)).toHaveValue("/held_compare_genes ");
    await expect(options(page)).toHaveCount(1);
    await expect(options(page).first()).toContainText("Type first");
    await expect(options(page).first()).toHaveAttribute("aria-disabled", "true");
    await box(page).press("Enter");
    await expect(box(page)).toHaveValue("/held_compare_genes ");
  });

  test("are written out by the server into the box, which is not sent, and is read before it is", async ({ page }) => {
    await setUp(page, "held", contextProgram());
    await look(page, "held");
    await openHome(page);
    const begun: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "POST" && new URL(request.url()).pathname.startsWith("/api/chats")) begun.push(request.url());
    });

    await box(page).fill("/held_summarize_gene TP53 depth=long");
    await expect.poll(() => listed(page)).toEqual(["/held_summarize_gene"]);
    await expect(options(page).first()).not.toHaveAttribute("aria-disabled", "true");
    const written = page.waitForResponse((response) => response.url().endsWith("/api/mcp/servers/held/render"));
    await box(page).press("Enter");

    expect((await written).request().postDataJSON()).toEqual({ prompt: "summarize_gene", arguments: { symbol: "TP53", depth: "long" } });
    await expect(box(page)).toHaveValue("Summarize what is known of the gene TP53, in a long answer.");
    await expect(menu(page)).toHaveCount(0);
    await expect(page).toHaveURL(/\/$/);
    expect(begun).toEqual([]);

    // The person can change it before it is sent
    await box(page).fill("Summarize what is known of the gene TP53, in a long answer, with its pathways.");
    await expect(box(page)).toHaveValue(/with its pathways\.$/);
  });

  test("with a part that the assistant says come out with who says each part, and the arguments are written one after another", async ({ page }) => {
    await setUp(page, "held", contextProgram());
    await look(page, "held");
    await openHome(page);

    await box(page).fill("/held_compare_genes TP53 second=BRCA1");
    await expect(options(page)).toHaveCount(1);
    await expect(options(page).first()).not.toHaveAttribute("aria-disabled", "true");
    await box(page).press("Enter");

    await expect(box(page)).toHaveValue(
      "User: Compare the genes TP53 and BRCA1.\n\nAssistant: I will compare what each does, and where they differ.",
    );
  });

  test("wait for an argument that is needed, which is said, and a name that the prompt does not take is part of the words", async ({ page }) => {
    await setUp(page, "held", contextProgram());
    await look(page, "held");
    await openHome(page);

    await box(page).fill("/held_compare_genes TP53");
    await expect(options(page).first()).toContainText("Add second=…");
    await expect(options(page).first()).toHaveAttribute("aria-disabled", "true");

    await box(page).fill("/held_compare_genes TP53 second=BRCA1 third=x");
    await expect(options(page).first()).not.toHaveAttribute("aria-disabled", "true");
    await box(page).press("Enter");
    await expect(box(page)).toHaveValue(/^User: Compare the genes TP53 and BRCA1 third=x\./);
  });

  test("are not offered for a server that is off, which new programs are not given", async ({ page }) => {
    await setUp(page, "held", contextProgram({ enabled: false }));
    await look(page, "held");
    await openHome(page);

    await box(page).fill("/held");

    await expect(menu(page)).toHaveCount(0);
  });

  test("are not offered for a server that was changed since it was looked at", async ({ page }) => {
    await setUp(page, "held", contextProgram());
    await look(page, "held");
    await setUp(page, "held", contextProgram({ env: { HELD_CHANGED: "yes" } }));
    await openHome(page);

    await box(page).fill("/held");

    await expect(menu(page)).toHaveCount(0);
  });

  test("are written out in a conversation that was given the server, and are sent as a message when the person sends it", async ({ page }) => {
    await setUp(page, "held", contextProgram());
    await look(page, "held");
    await openChat(page, "MCP: a prompt in a conversation", ["held"]);

    await box(page).fill("/held_comp");
    await expect.poll(() => listed(page)).toEqual(["/held_compare_genes"]);
    await box(page).fill("/held_compare_genes TP53 second=BRCA1");
    await box(page).press("Enter");

    await expect(box(page)).toHaveValue(/^User: Compare the genes TP53 and BRCA1\./);
    await expect(page.getByTestId("user-message")).toHaveCount(0);
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await expect(page.getByTestId("user-message").last()).toContainText("Compare the genes TP53 and BRCA1.");
    await expect(box(page)).toHaveValue("");
  });

  test("are not offered in a conversation that was not given the server", async ({ page }) => {
    await setUp(page, "held", contextProgram());
    await look(page, "held");
    await openChat(page, "MCP: a conversation without the server", []);

    // The servers are read when a slash is first written, so what is not there is looked for after that
    const read = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/mcp" && response.request().method() === "GET");
    await box(page).fill("/held");
    await read;

    await expect(menu(page)).toHaveCount(0);
  });

  test("that the server could not write out leave what was typed in the box, and say so", async ({ page }) => {
    const away = await HttpServer.started("--context");
    try {
      await setUp(page, "heldaway", away.entry);
      await look(page, "heldaway");
      await openHome(page);
      await box(page).fill("/heldaway_summarize_gene TP53");
      await expect.poll(() => listed(page)).toEqual(["/heldaway_summarize_gene"]);
    } finally {
      away.stop();
    }
    await expect
      .poll(async () => {
        try {
          await away.stats();

          return "up";
        } catch {
          return "gone";
        }
      })
      .toBe("gone");

    await box(page).press("Enter");

    await expect(page.getByRole("alert").filter({ hasText: "Could not connect to the MCP server heldaway" })).toBeVisible();
    await expect(box(page)).toHaveValue("/heldaway_summarize_gene TP53");
    await expect(page).toHaveURL(/\/$/);
  });
});
