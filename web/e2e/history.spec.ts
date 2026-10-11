import { randomBytes } from "node:crypto";
import type { Page } from "@playwright/test";
import { expect, HOME_HEADING, test } from "./fixtures";

// Every conversation the tests make is listed for all of them, so a title that only one test has keeps what it looks for
// from being found in another's
const tag = () => randomBytes(3).toString("hex");

const refused = (code: string, message: string, status = 422) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify({ error: { code, message } }),
});

// The list looks again every five seconds, which would show a change that the page never asked to see, so the
// tests turn that off and have the page look when it is told to
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const every = window.setInterval.bind(window);
    window.setInterval = ((handler: TimerHandler, ms?: number, ...args: unknown[]) =>
      ms === 5000 ? 0 : every(handler, ms, ...args)) as typeof window.setInterval;
  });
});

const list = (page: Page) => page.getByRole("navigation", { name: "Conversations" });
// A conversation's row is told by its id, which a title that is changed leaves as it was
const row = (page: Page, id: string) => list(page).locator(`[data-chat-id="${id}"]`);
const options = (page: Page, id: string) => row(page, id).getByRole("button", { name: "Conversation options" });
const titleField = (page: Page) => page.getByRole("textbox", { name: "Conversation title" });

// Makes a conversation through the server, and has the page look at the list again so that it is there
async function make(page: Page, title: string): Promise<string> {
  const made = await page.request.post("/api/chats", { data: { title } });
  expect(made.status()).toBe(201);
  const id: string = (await made.json()).id;
  await page.reload();
  // On a narrow screen the list is in a drawer that is not open yet, and what is hidden is not found by its role
  await expect(page.locator(`[data-chat-id="${id}"]`)).toBeAttached();

  return id;
}

async function titleOnServer(page: Page, id: string): Promise<string | null> {
  const found = await page.request.get(`/api/chats/${id}`);

  return found.status() === 200 ? (await found.json()).title : null;
}

async function chooseFrom(page: Page, id: string, item: "Rename" | "Delete"): Promise<void> {
  await options(page, id).click();
  await page.getByRole("menuitem", { name: item }).click();
  // It is shut, and gone, before anything is done next: one still being drawn as it goes is opened again by a click
  await expect(page.getByRole("menu")).toHaveCount(0);
}

const DAY = 24 * 60 * 60 * 1000;

const idOf = (title: string) => title.toLowerCase().replaceAll(" ", "-");

function listed(title: string, updated: Date, state = "ready") {
  return {
    id: idOf(title),
    title,
    created_at: updated.toISOString(),
    updated_at: updated.toISOString(),
    state,
    turns: 1,
    spent: null,
    max_cost: null,
    model: null,
  };
}

// The list as the server would give it, for a test that needs the days and the number of them to be what it says
async function listing(page: Page, chats: ReturnType<typeof listed>[]): Promise<void> {
  await page.route("**/api/chats", (route) =>
    route.request().method() === "GET" ? route.fulfill({ json: { chats } }) : route.continue(),
  );
  await page.reload();
  await expect(page.locator('nav[aria-label="Conversations"] a').first()).toBeAttached();
}

test.describe("the list of conversations", () => {
  test("is in days, today first, and a day with nothing in it is left out", async ({ page }) => {
    const now = new Date();
    const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    await listing(page, [
      listed("Asked just now", now),
      listed("Asked the day before", new Date(midnight - DAY / 2)),
      listed("Asked a few days ago", new Date(midnight - 3.5 * DAY)),
      listed("Asked long ago", new Date(midnight - 40 * DAY)),
    ]);

    await expect(list(page).getByRole("heading")).toHaveText(["Today", "Yesterday", "Previous 7 days", "Earlier"]);
    const links = await list(page).getByRole("link").allInnerTexts();
    expect(links.map((text) => text.split("\n")[0])).toEqual([
      "Asked just now",
      "Asked the day before",
      "Asked a few days ago",
      "Asked long ago",
    ]);

    await listing(page, [listed("Asked long ago", new Date(midnight - 40 * DAY)), listed("Asked just now", now)]);

    await expect(list(page).getByRole("heading")).toHaveText(["Today", "Earlier"]);
  });

  test("can be searched once there are enough to need it, by the words of a title in any order", async ({ page }) => {
    const now = new Date();
    const titles = [
      "Nanobody epitope mapping",
      "CRISPR base editing screen",
      "Single-cell clustering of T cells",
      "Protein folding energies",
      "Docking an antibody",
      "Plasmid design",
      "GWAS quality control",
    ];
    await listing(page, titles.map((title, index) => listed(title, new Date(now.getTime() - index * 1000))));
    await expect(page.getByRole("searchbox", { name: "Search conversations" })).toHaveCount(0);

    await listing(page, [...titles, "Western blot troubleshooting"].map((title, index) => listed(title, new Date(now.getTime() - index * 1000))));
    const search = page.getByRole("searchbox", { name: "Search conversations" });
    await expect(search).toBeVisible();
    await expect(list(page).getByRole("link")).toHaveCount(8);

    await search.fill("EDITING crispr");
    await expect(list(page).getByRole("link")).toHaveCount(1);
    await expect(list(page).getByRole("link")).toContainText("CRISPR base editing screen");

    await search.fill("zzz");
    await expect(list(page).getByRole("link")).toHaveCount(0);
    await expect(list(page).getByText("No conversation has all of those words in its title.")).toBeVisible();

    await page.getByRole("button", { name: "Clear the search" }).click();
    await expect(search).toHaveValue("");
    await expect(list(page).getByRole("link")).toHaveCount(8);

    // Typing, which is more than a box being filled, leaves what is typed in it
    await search.pressSequentially("cell");
    await expect(search).toHaveValue("cell");
    await expect(list(page).getByRole("link")).toHaveCount(1);
    await search.press("Escape");
    await expect(search).toHaveValue("");
    await expect(page.getByRole("button", { name: "Clear the search" })).toHaveCount(0);
    await expect(list(page).getByRole("link")).toHaveCount(8);
  });

  test("is not searched by what was typed once there are too few to need a search", async ({ page }) => {
    const now = new Date();
    const titles = Array.from({ length: 8 }, (_, index) => `Question number ${index + 1}`);
    const all = titles.map((title, index) => listed(title, new Date(now.getTime() - index * 1000)));
    await listing(page, all);
    await page.getByRole("searchbox", { name: "Search conversations" }).fill("number 3");
    await expect(list(page).getByRole("link")).toHaveCount(1);

    // Another page deletes one, which leaves seven: too few to need a search, so what is still typed in the box, which
    // is no longer shown, is not held against them
    await page.unroute("**/api/chats");
    await page.route("**/api/chats", (route) =>
      route.request().method() === "GET" ? route.fulfill({ json: { chats: all.slice(0, 7) } }) : route.continue(),
    );
    await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));

    await expect(page.getByRole("searchbox", { name: "Search conversations" })).toHaveCount(0);
    await expect(list(page).getByRole("link")).toHaveCount(7);
  });

  test("says that one is at work when it is going to be deleted", async ({ page }) => {
    await listing(page, [listed("Still going", new Date(), "running"), listed("Finished", new Date(Date.now() - 1000))]);

    await chooseFrom(page, idOf("Finished"), "Delete");
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("“Finished” is removed with its messages, its files, and what it ran.");
    await expect(dialog).not.toContainText("at work");
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();

    await chooseFrom(page, idOf("Still going"), "Delete");
    await expect(dialog).toContainText("It is at work now, and that is stopped.");
  });
});

test.describe("renaming a conversation", () => {
  test("is done where it is listed, and the title is kept as the server keeps it", async ({ page }) => {
    const title = `Rename ${tag()}`;
    const id = await make(page, title);

    await chooseFrom(page, id, "Rename");
    const field = titleField(page);
    await expect(field).toBeFocused();
    await expect(field).toHaveValue(title);
    // What the options are for is not there to be used while the title is
    await expect(options(page, id)).toBeHidden();
    // What is there is selected, so that typing replaces it
    await page.keyboard.type(`  Quokka   ${title}  `);
    await page.keyboard.press("Enter");

    const renamed = `Quokka ${title}`;
    await expect(field).toHaveCount(0);
    await expect(list(page).getByRole("link", { name: renamed })).toBeVisible();
    await expect(list(page).getByRole("link", { name: new RegExp(`^${title}`) })).toHaveCount(0);
    await expect(options(page, id)).toBeFocused();
    expect(await titleOnServer(page, id)).toBe(renamed);

    await page.reload();
    await expect(list(page).getByRole("link", { name: renamed })).toBeVisible();
  });

  test("is no longer than a title may be, in characters", async ({ page }) => {
    const title = `Long ${tag()}`;
    const id = await make(page, title);

    await chooseFrom(page, id, "Rename");
    await titleField(page).fill("x".repeat(120));
    await expect(titleField(page)).toHaveValue("x".repeat(80));
    await page.keyboard.press("Enter");

    await expect(options(page, id)).toBeAttached();
    expect(await titleOnServer(page, id)).toBe("x".repeat(80));

    // Characters that are two units long are as much one as any, so there is room for as many of them
    await chooseFrom(page, id, "Rename");
    await titleField(page).fill("😀".repeat(70));
    await expect(titleField(page)).toHaveValue("😀".repeat(70));
    await titleField(page).fill("😀".repeat(90));
    await expect(titleField(page)).toHaveValue("😀".repeat(80));
    await page.keyboard.press("Enter");

    await expect(titleField(page)).toHaveCount(0);
    expect(await titleOnServer(page, id)).toBe("😀".repeat(80));
  });

  test("changes the heading of the conversation that is open", async ({ page }) => {
    const title = `Open ${tag()}`;
    const id = await make(page, title);
    await page.goto(`/chat?id=${id}`);
    await expect(page.getByTestId("chat-title")).toHaveText(title);

    await chooseFrom(page, id, "Rename");
    await page.keyboard.type(`Renamed ${title}`);
    await page.keyboard.press("Enter");

    await expect(page.getByTestId("chat-title")).toHaveText(`Renamed ${title}`);
    await expect(page).toHaveTitle(`Renamed ${title} · Virtual Lab`);
    await expect(list(page).getByRole("link", { name: `Renamed ${title}` })).toHaveAttribute("aria-current", "page");
  });

  test("is given up with Escape, and a title with nothing in it or the same one changes nothing", async ({ page }) => {
    const title = `Unchanged ${tag()}`;
    const id = await make(page, title);
    let asked = 0;
    await page.route("**/api/chats/*", (route) => {
      if (route.request().method() === "PATCH") asked += 1;
      return route.continue();
    });

    await chooseFrom(page, id, "Rename");
    await page.keyboard.type("Something else");
    await page.keyboard.press("Escape");
    await expect(titleField(page)).toHaveCount(0);
    await expect(list(page).getByRole("link", { name: title })).toBeVisible();
    await expect(options(page, id)).toBeFocused();

    // Escape gives it up when there is nothing in the box too, and does not wait to be typed over
    await chooseFrom(page, id, "Rename");
    await titleField(page).fill("");
    await titleField(page).press("Escape");
    await expect(titleField(page)).toHaveCount(0);
    await expect(list(page).getByRole("link", { name: title })).toBeVisible();

    await chooseFrom(page, id, "Rename");
    await titleField(page).fill("   \n  ");
    await titleField(page).press("Enter");
    await expect(titleField(page)).toHaveCount(0);
    await expect(list(page).getByRole("link", { name: title })).toBeVisible();
    await expect(options(page, id)).toBeFocused();

    await chooseFrom(page, id, "Rename");
    await titleField(page).press("Enter");
    await expect(titleField(page)).toHaveCount(0);
    await expect(list(page).getByRole("link", { name: title })).toBeVisible();

    expect(asked).toBe(0);

    // A menu that was shut with Escape, after one that was shut by choosing, gives the focus back like the first did
    await options(page, id).click();
    await expect(page.getByRole("menuitem", { name: "Rename" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("menu")).toHaveCount(0);
    await expect(options(page, id)).toBeFocused();
  });

  test("is kept when the focus goes elsewhere, and a title that is not changed leaves the focus where it went", async ({ page }) => {
    const title = `Blurred ${tag()}`;
    const id = await make(page, title);
    let asked = 0;
    await page.route("**/api/chats/*", (route) => {
      if (route.request().method() === "PATCH") asked += 1;
      return route.continue();
    });

    await chooseFrom(page, id, "Rename");
    await page.getByRole("textbox", { name: "Message" }).click();
    await expect(titleField(page)).toHaveCount(0);
    await expect(page.getByRole("textbox", { name: "Message" })).toBeFocused();
    expect(asked).toBe(0);

    await chooseFrom(page, id, "Rename");
    await page.keyboard.type(`Kept ${title}`);
    await page.getByRole("textbox", { name: "Message" }).click();

    await expect(list(page).getByRole("link", { name: `Kept ${title}` })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Message" })).toBeFocused();
    expect(await titleOnServer(page, id)).toBe(`Kept ${title}`);
    expect(asked).toBe(1);
  });

  test("is asked of the server once, when the focus goes elsewhere before the server has answered", async ({ page }) => {
    const title = `Quick ${tag()}`;
    const id = await make(page, title);
    let asked = 0;
    let answer = () => {};
    const waiting = new Promise<void>((resolve) => (answer = resolve));
    await page.route("**/api/chats/*", async (route) => {
      if (route.request().method() !== "PATCH") return route.continue();
      asked += 1;
      await waiting;
      return route.continue();
    });

    await chooseFrom(page, id, "Rename");
    await page.keyboard.type(`Once ${title}`);
    await page.keyboard.press("Enter");
    await expect(titleField(page)).toHaveAttribute("readonly", "");
    await page.getByRole("textbox", { name: "Message" }).click();
    // Time for a second request to be made if one is going to be
    await page.waitForTimeout(300);
    answer();

    await expect(list(page).getByRole("link", { name: `Once ${title}` })).toBeVisible();
    expect(asked).toBe(1);
    expect(await titleOnServer(page, id)).toBe(`Once ${title}`);
  });

  test("says why the server refused a title, and keeps what was typed to try again", async ({ page }) => {
    const title = `Refused ${tag()}`;
    const id = await make(page, title);
    await page.route("**/api/chats/*", (route) =>
      route.request().method() === "PATCH" ? route.fulfill(refused("invalid", "That title is not allowed.")) : route.continue(),
    );

    await chooseFrom(page, id, "Rename");
    await page.keyboard.type(`Second try ${title}`);
    await page.keyboard.press("Enter");

    await expect(list(page).getByRole("alert")).toHaveText("That title is not allowed.");
    await expect(titleField(page)).toHaveValue(`Second try ${title}`);
    await expect(titleField(page)).toBeFocused();
    await expect(titleField(page)).toHaveAttribute("aria-invalid", "true");

    // What was said is taken back while the title is tried again, and not left to be read with what comes of it
    await page.unroute("**/api/chats/*");
    let answer = () => {};
    const waiting = new Promise<void>((resolve) => (answer = resolve));
    await page.route("**/api/chats/*", async (route) => {
      if (route.request().method() !== "PATCH") return route.continue();
      await waiting;
      return route.continue();
    });
    await page.keyboard.press("Enter");
    await expect(titleField(page)).toHaveAttribute("readonly", "");
    await expect(list(page).getByRole("alert")).toHaveCount(0);
    answer();

    await expect(titleField(page)).toHaveCount(0);
    await expect(list(page).getByRole("link", { name: `Second try ${title}` })).toBeVisible();
    expect(await titleOnServer(page, id)).toBe(`Second try ${title}`);
  });
});

test.describe("deleting a conversation", () => {
  test("asks first, and a conversation that is kept is as it was", async ({ page }) => {
    const title = `Keep ${tag()}`;
    const id = await make(page, title);
    let asked = 0;
    await page.route("**/api/chats/*", (route) => {
      if (route.request().method() === "DELETE") asked += 1;
      return route.continue();
    });

    await chooseFrom(page, id, "Delete");
    const dialog = page.getByRole("alertdialog", { name: "Delete this conversation?" });
    await expect(dialog).toContainText(`“${title}” is removed with its messages, its files, and what it ran. This cannot be undone.`);
    // The safe answer is the one the focus is on
    await expect(dialog.getByRole("button", { name: "Keep it" })).toBeFocused();

    await dialog.getByRole("button", { name: "Keep it" }).click();
    await expect(dialog).toBeHidden();
    await expect(options(page, id)).toBeFocused();

    await chooseFrom(page, id, "Delete");
    await expect(dialog).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();

    expect(asked).toBe(0);
    expect(await titleOnServer(page, id)).toBe(title);
    await expect(list(page).getByRole("link", { name: title })).toBeVisible();
    // The page can still be used, which it cannot be if it was left with its pointer events taken
    await expect(page.locator("body")).not.toHaveCSS("pointer-events", "none");
  });

  test("removes it from the list and from the server", async ({ page }) => {
    const title = `Delete ${tag()}`;
    const id = await make(page, title);

    await chooseFrom(page, id, "Delete");
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();

    await expect(page.getByRole("alertdialog")).toBeHidden();
    await expect(options(page, id)).toHaveCount(0);
    expect(await titleOnServer(page, id)).toBeNull();
    // The row that had the focus is gone, and the focus is not left with it
    await expect(list(page)).toBeFocused();
    // It was not the one that is open, so the page is where it was
    await expect(page.getByRole("heading", { name: HOME_HEADING })).toBeVisible();
  });

  test("leaves the conversation that is open for the home page when that is the one", async ({ page }) => {
    const title = `Open ${tag()}`;
    const other = `Other ${tag()}`;
    const id = await make(page, title);
    const otherId = await make(page, other);
    await page.goto(`/chat?id=${id}`);
    await expect(page.getByTestId("chat-title")).toHaveText(title);

    await chooseFrom(page, otherId, "Delete");
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();
    await expect(options(page, otherId)).toHaveCount(0);
    // A page that is going somewhere else takes a moment to be gone from
    await page.waitForTimeout(500);
    await expect(page).toHaveURL(new RegExp(`/chat\\?id=${id}$`));
    await expect(page.getByTestId("chat-title")).toHaveText(title);

    await chooseFrom(page, id, "Delete");
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();

    await expect(page.getByRole("heading", { name: HOME_HEADING })).toBeVisible();
    await expect(page).not.toHaveURL(/chat/);
    await expect(options(page, id)).toHaveCount(0);
    expect(await titleOnServer(page, id)).toBeNull();
  });

  test("says why the server would not, and stays until it is answered", async ({ page }) => {
    const title = `Refused ${tag()}`;
    const id = await make(page, title);
    await page.route("**/api/chats/*", (route) =>
      route.request().method() === "DELETE" ? route.fulfill(refused("busy", "It cannot be deleted just now.", 409)) : route.continue(),
    );
    const dialog = page.getByRole("alertdialog");

    await chooseFrom(page, id, "Delete");
    await dialog.getByRole("button", { name: "Delete" }).click();

    await expect(dialog.getByRole("alert")).toHaveText("It cannot be deleted just now.");
    await expect(dialog.getByRole("button", { name: "Delete" })).toBeEnabled();
    expect(await titleOnServer(page, id)).toBe(title);

    // What was said is not said again when the question is asked again
    await dialog.getByRole("button", { name: "Keep it" }).click();
    await expect(dialog).toBeHidden();
    await chooseFrom(page, id, "Delete");
    await expect(dialog.getByRole("alert")).toHaveCount(0);

    await page.unroute("**/api/chats/*");
    await dialog.getByRole("button", { name: "Delete" }).click();
    await expect(dialog).toBeHidden();
    await expect(options(page, id)).toHaveCount(0);
    expect(await titleOnServer(page, id)).toBeNull();
  });

  test("is done when it is already done, which another page may have done", async ({ page }) => {
    const title = `Gone ${tag()}`;
    const id = await make(page, title);

    await chooseFrom(page, id, "Delete");
    expect((await page.request.delete(`/api/chats/${id}`)).status()).toBe(204);
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();

    await expect(page.getByRole("alertdialog")).toBeHidden();
    await expect(options(page, id)).toHaveCount(0);
  });

  test("holds the dialog while the server is answering, and does not ask twice", async ({ page }) => {
    const title = `Slow ${tag()}`;
    const id = await make(page, title);
    let asked = 0;
    let answer = () => {};
    const waiting = new Promise<void>((resolve) => (answer = resolve));
    await page.route("**/api/chats/*", async (route) => {
      if (route.request().method() !== "DELETE") return route.continue();
      asked += 1;
      await waiting;
      return route.continue();
    });
    const dialog = page.getByRole("alertdialog");

    await chooseFrom(page, id, "Delete");
    await dialog.getByRole("button", { name: "Delete" }).click();
    await expect(dialog.getByRole("button", { name: "Deleting…" })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Keep it" })).toBeDisabled();
    await page.keyboard.press("Escape");
    // It takes a moment to be drawn as it goes, and it is not going
    await page.waitForTimeout(300);
    await expect(dialog).toBeVisible();
    expect(asked).toBe(1);

    answer();
    await expect(dialog).toBeHidden();
    await expect(options(page, id)).toHaveCount(0);
    expect(asked).toBe(1);
  });
});

test.describe("the list on a narrow screen", () => {
  test.use({ viewport: { width: 390, height: 800 } });

  test("keeps the drawer open for an Escape that a menu, a title, or a search takes", async ({ page }) => {
    const title = `Drawer ${tag()}`;
    const id = await make(page, title);
    const drawer = page.getByRole("complementary", { name: "Sidebar" });
    await page.getByRole("button", { name: "Show the conversations" }).click();
    await expect(drawer).toBeVisible();

    await options(page, id).click();
    await expect(page.getByRole("menuitem", { name: "Rename" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("menuitem", { name: "Rename" })).toBeHidden();
    await expect(drawer).toBeVisible();
    await expect(options(page, id)).toBeFocused();

    await chooseFrom(page, id, "Rename");
    await expect(titleField(page)).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(titleField(page)).toHaveCount(0);
    await expect(drawer).toBeVisible();

    await chooseFrom(page, id, "Delete");
    await page.keyboard.press("Escape");
    await expect(page.getByRole("alertdialog")).toBeHidden();
    await expect(drawer).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
  });

  test("keeps the drawer open for the Escape that empties the search, and closes it for the next", async ({ page }) => {
    const now = new Date();
    await listing(page, Array.from({ length: 9 }, (_, index) => listed(`Search drawer ${index}`, new Date(now.getTime() - index * 1000))));
    const drawer = page.getByRole("complementary", { name: "Sidebar" });
    await page.getByRole("button", { name: "Show the conversations" }).click();
    const search = page.getByRole("searchbox", { name: "Search conversations" });

    await search.fill("drawer 3");
    await search.press("Escape");
    await expect(search).toHaveValue("");
    await expect(drawer).toBeVisible();

    await search.press("Escape");
    await expect(drawer).toBeHidden();
  });
});

test.describe("the list on a screen that is touched", () => {
  test.use({ viewport: { width: 390, height: 800 }, hasTouch: true, isMobile: true });

  test("shows what can be done to a conversation without a pointer to rest on it", async ({ page }) => {
    const title = `Touch ${tag()}`;
    const id = await make(page, title);
    await page.getByRole("button", { name: "Show the conversations" }).click();

    await expect(options(page, id)).toHaveCSS("opacity", "1");
  });
});

test.describe("on a wide screen", () => {
  test("what can be done to a conversation is shown when it is pointed at or reached by keyboard", async ({ page }) => {
    const title = `Reveal ${tag()}`;
    const id = await make(page, title);
    const button = options(page, id);

    await page.mouse.move(600, 400);
    await expect(button).toHaveCSS("opacity", "0");
    await list(page).getByRole("link", { name: title }).hover();
    await expect(button).toHaveCSS("opacity", "1");

    await page.mouse.move(600, 400);
    await expect(button).toHaveCSS("opacity", "0");
    await list(page).getByRole("link", { name: title }).focus();
    await expect(button).toHaveCSS("opacity", "1");
  });
});
