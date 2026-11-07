import { randomBytes } from "node:crypto";
import type { Page } from "@playwright/test";
import { accessibilityProblems } from "../axe";
import { answered, expect, HOME_HEADING, test } from "../fixtures";

// A campaign is listed on the side of every page, and between the programs of the tests that count what is there, so these
// are on the server of their own, one after another, and each takes away the campaigns it made
test.describe.configure({ mode: "serial" });

const tag = () => randomBytes(3).toString("hex");

const message = (page: Page) => page.getByRole("textbox", { name: "Message" });
const list = (page: Page) => page.getByRole("navigation", { name: "Programs" });
const group = (page: Page, id: string) => page.locator(`[data-testid="campaign-group"][data-campaign-id="${id}"]`);
// A program's row on the side is told by its id, which a title that is changed leaves as it was
const row = (page: Page, id: string) => list(page).locator(`[data-chat-id="${id}"]`);
const dialog = (page: Page) => page.getByTestId("campaign-dialog");
const mover = (page: Page) => page.getByTestId("move-dialog");

interface Made {
  id: string;
  name: string;
  brief: string;
}

async function removeCampaigns(page: Page): Promise<void> {
  const { campaigns } = await (await page.request.get("/api/campaigns")).json();
  for (const campaign of campaigns) {
    expect((await page.request.delete(`/api/campaigns/${campaign.id}`)).ok()).toBe(true);
  }
}

test.beforeEach(async ({ page }) => {
  await removeCampaigns(page);
});

test.afterEach(async ({ page }) => {
  await removeCampaigns(page);
});

async function makeCampaign(page: Page, label: string, brief = ""): Promise<Made> {
  const name = `${label} ${tag()}`;
  const made = await page.request.post("/api/campaigns", { data: { name, brief } });
  expect(made.status()).toBe(201);

  return { id: (await made.json()).id, name, brief };
}

// A program made through the server, titled at once, since every test's programs are listed for all of them
async function makeProgram(page: Page, label: string, campaign?: string): Promise<{ id: string; title: string }> {
  const title = `${label} ${tag()}`;
  const made = await page.request.post("/api/chats", { data: { title, ...(campaign === undefined ? {} : { campaign }) } });
  expect(made.status()).toBe(201);

  return { id: (await made.json()).id, title };
}

async function infoOf(page: Page, id: string) {
  const found = await page.request.get(`/api/chats/${id}`);
  expect(found.status()).toBe(200);

  return found.json();
}

async function campaignOf(page: Page, id: string): Promise<string | null> {
  const { chats } = await (await page.request.get("/api/chats")).json();

  return chats.find((chat: { id: string }) => chat.id === id)?.campaign ?? null;
}

// Moves a program from its row on the side, through the menu of the row
async function moveFromList(page: Page, id: string, to: string): Promise<void> {
  await row(page, id).getByRole("button", { name: "Program options" }).click();
  await page.getByRole("menuitem", { name: "Move to campaign…" }).click();
  await expect(page.getByRole("menu")).toHaveCount(0);
  await chooseAndMove(page, to);
}

async function chooseAndMove(page: Page, to: string): Promise<void> {
  await expect(mover(page)).toBeVisible();
  await mover(page).getByRole("radio", { name: to, exact: true }).check();
  await mover(page).getByTestId("move-save").click();
  await expect(mover(page)).toHaveCount(0);
}

test.describe("making a campaign", () => {
  test("is from the side, with a name and a goal, and opens its page", async ({ page }) => {
    const name = `Nanobody screen ${tag()}`;
    const brief = `Find a binder of the KP.3 spike, ${tag()}.`;

    await page.getByRole("button", { name: "New campaign" }).click();
    await expect(dialog(page)).toBeVisible();
    await dialog(page).getByRole("textbox", { name: "Name" }).fill(name);
    await dialog(page).getByRole("textbox", { name: "Goal" }).fill(`  ${brief}\n`);
    await dialog(page).getByTestId("campaign-save").click();

    await page.waitForURL(/\/campaign\?id=/);
    const id = new URL(page.url()).searchParams.get("id") ?? "";
    await expect(page.getByTestId("campaign-title")).toHaveText(name);
    await expect(page.getByTestId("campaign-brief")).toHaveText(brief);
    await expect(page.getByTestId("campaign-totals")).toContainText("0 programs");
    await expect(page.getByText("No program is part of this campaign yet.")).toBeVisible();
    await expect(group(page, id).getByRole("link", { name })).toHaveAttribute("aria-current", "page");
    await expect(group(page, id).getByRole("link", { name })).toContainText("0");

    const made = await (await page.request.get(`/api/campaigns/${id}`)).json();
    expect(made).toMatchObject({ name, brief, programs: [], spent: 0 });
  });

  test("is not made without a name, or with a goal that is too long, and nothing is asked of the server until it is right", async ({ page }) => {
    let made = 0;
    page.on("request", (request) => {
      if (request.method() === "POST" && new URL(request.url()).pathname === "/api/campaigns") made += 1;
    });

    await page.getByRole("button", { name: "New campaign" }).click();
    await dialog(page).getByTestId("campaign-save").click();
    const name = dialog(page).getByRole("textbox", { name: "Name" });
    await expect(dialog(page).getByText("A campaign needs a name.")).toBeVisible();
    await expect(name).toBeFocused();
    await expect(name).toHaveAttribute("aria-invalid", "true");

    await name.fill(`Named ${tag()}`);
    await expect(dialog(page).getByText("A campaign needs a name.")).toHaveCount(0);
    await dialog(page).getByRole("textbox", { name: "Goal" }).fill("a".repeat(8001));
    await dialog(page).getByTestId("campaign-save").click();
    await expect(dialog(page).getByText("The goal is at most 8,000 characters, and this is 8,001.")).toBeVisible();
    await expect(dialog(page).getByRole("textbox", { name: "Goal" })).toBeFocused();

    expect(made).toBe(0);
    await dialog(page).getByRole("button", { name: "Cancel" }).click();
    await expect(dialog(page)).toHaveCount(0);
    await expect(page).not.toHaveURL(/\/campaign/);
  });

  test("is not made again under a name that a campaign has, whatever the case, and says so", async ({ page }) => {
    const first = await makeCampaign(page, "Kinase panel");
    await page.reload();

    await page.getByRole("button", { name: "New campaign" }).click();
    await dialog(page).getByRole("textbox", { name: "Name" }).fill(first.name.toUpperCase());
    await dialog(page).getByTestId("campaign-save").click();

    await expect(dialog(page).getByText(/There is a campaign called .* already/)).toBeVisible();
    await expect(dialog(page)).toBeVisible();
    await expect(page).not.toHaveURL(/\/campaign/);
    const { campaigns } = await (await page.request.get("/api/campaigns")).json();
    expect(campaigns).toHaveLength(1);
  });
});

test.describe("a program of a campaign", () => {
  test("is begun in one from the home page, and its lead is told the goal", async ({ page }) => {
    const campaign = await makeCampaign(page, "Affinity ranking", `Rank the candidates by affinity first, ${tag()}.`);
    await page.goto("/");

    const choice = page.getByRole("combobox", { name: "Campaign" });
    await expect(choice).toHaveValue("");
    await expect(page.getByTestId("program-campaign-goal")).toHaveCount(0);
    await choice.selectOption(campaign.id);
    await expect(page.getByTestId("program-campaign-goal")).toContainText(campaign.brief);

    await message(page).fill("campaign: what were you told of it?");
    await page.getByRole("button", { name: "Send" }).click();
    await page.waitForURL(/\/chat\?id=/);
    const id = new URL(page.url()).searchParams.get("id") ?? "";
    await answered(page, `Given campaign ${campaign.name}: ${campaign.brief}`);

    expect(await infoOf(page, id)).toMatchObject({ config: { campaign: campaign.id } });
    expect(await campaignOf(page, id)).toBe(campaign.id);
    await expect(page.getByTestId("program-campaign-button")).toHaveText(campaign.name);
    await expect(group(page, campaign.id).locator(`[data-chat-id="${id}"]`)).toBeVisible();
    await expect(group(page, campaign.id).getByRole("link", { name: campaign.name })).toContainText("1");
  });

  test("is begun in one from the campaign's page, which the home page has chosen", async ({ page }) => {
    const campaign = await makeCampaign(page, "Stability", `Keep what is stable at 37 degrees, ${tag()}.`);
    await page.goto(`/campaign?id=${campaign.id}`);

    await page.getByTestId("campaign-new-program").click();
    await expect(page).toHaveURL(new RegExp(`/\\?campaign=${campaign.id}$`));
    await expect(page.getByRole("combobox", { name: "Campaign" })).toHaveValue(campaign.id);
    await expect(page.getByTestId("program-campaign-goal")).toContainText(campaign.brief);

    await message(page).fill("campaign: and here?");
    await page.getByRole("button", { name: "Send" }).click();
    await page.waitForURL(/\/chat\?id=/);
    await answered(page, `Given campaign ${campaign.name}: ${campaign.brief}`);
  });

  test("is begun in none where none is chosen, and its lead is told of none", async ({ page }) => {
    await makeCampaign(page, "Left alone", "Never to be told.");
    await page.goto("/");
    await expect(page.getByRole("combobox", { name: "Campaign" })).toHaveValue("");

    await message(page).fill("campaign: what were you told?");
    await page.getByRole("button", { name: "Send" }).click();
    await page.waitForURL(/\/chat\?id=/);
    const id = new URL(page.url()).searchParams.get("id") ?? "";
    await answered(page, "Given no campaign");

    expect(await campaignOf(page, id)).toBeNull();
    await expect(page.getByTestId("program-campaign-button")).toHaveText("Add to a campaign");
  });

  test("is moved from its row on the side to a campaign, to another, and out of it, and shows where it is", async ({ page }) => {
    const first = await makeCampaign(page, "First", "Goal of the first.");
    const second = await makeCampaign(page, "Second", "Goal of the second.");
    const program = await makeProgram(page, "Wandering");
    await page.goto(`/chat?id=${program.id}`);
    await expect(row(page, program.id)).toBeVisible();
    await expect(group(page, first.id).locator(`[data-chat-id="${program.id}"]`)).toHaveCount(0);

    await moveFromList(page, program.id, first.name);
    await expect(group(page, first.id).locator(`[data-chat-id="${program.id}"]`)).toBeVisible();
    await expect(page.getByTestId("program-campaign-button")).toHaveText(first.name);
    expect(await campaignOf(page, program.id)).toBe(first.id);

    await moveFromList(page, program.id, second.name);
    await expect(group(page, first.id).locator(`[data-chat-id="${program.id}"]`)).toHaveCount(0);
    await expect(group(page, second.id).locator(`[data-chat-id="${program.id}"]`)).toBeVisible();
    await expect(page.getByTestId("program-campaign-button")).toHaveText(second.name);
    expect(await campaignOf(page, program.id)).toBe(second.id);

    await moveFromList(page, program.id, "No campaign");
    await expect(group(page, second.id).locator(`[data-chat-id="${program.id}"]`)).toHaveCount(0);
    await expect(row(page, program.id)).toBeVisible();
    await expect(page.getByTestId("program-campaign-button")).toHaveText("Add to a campaign");
    expect(await campaignOf(page, program.id)).toBeNull();
  });

  test("is moved from its own page, where a campaign can be made on the way", async ({ page }) => {
    const existing = await makeCampaign(page, "Existing");
    const program = await makeProgram(page, "Moved on its page");
    await page.goto(`/chat?id=${program.id}`);

    await page.getByTestId("program-campaign-button").click();
    await expect(mover(page)).toBeVisible();
    await expect(mover(page).getByTestId("move-save")).toBeDisabled();
    await expect(mover(page).getByRole("radio", { name: "No campaign" })).toBeChecked();

    const made = `Made on the way ${tag()}`;
    await mover(page).getByTestId("move-new-campaign").click();
    await dialog(page).getByRole("textbox", { name: "Name" }).fill(made);
    await dialog(page).getByTestId("campaign-save").click();
    await expect(dialog(page)).toHaveCount(0);
    await expect(mover(page).getByRole("radio", { name: made, exact: true })).toBeChecked();
    await expect(mover(page).getByRole("radio", { name: existing.name, exact: true })).not.toBeChecked();

    await mover(page).getByTestId("move-save").click();
    await expect(mover(page)).toHaveCount(0);
    await expect(page.getByTestId("program-campaign-button")).toHaveText(made);

    const { campaigns } = await (await page.request.get("/api/campaigns")).json();
    const id = campaigns.find((campaign: { name: string }) => campaign.name === made).id;
    expect(await campaignOf(page, program.id)).toBe(id);
  });

  test("is moved out of a campaign from the campaign's page, and the page then counts one less", async ({ page }) => {
    const campaign = await makeCampaign(page, "Counted");
    const staying = await makeProgram(page, "Staying", campaign.id);
    const leaving = await makeProgram(page, "Leaving", campaign.id);
    await page.goto(`/campaign?id=${campaign.id}`);

    const programs = page.getByRole("list", { name: "Programs of the campaign" });
    await expect(page.getByTestId("campaign-totals")).toContainText("2 programs");
    await expect(programs.locator("li")).toHaveCount(2);

    await programs.getByRole("button", { name: `Change the campaign of ${leaving.title}` }).click();
    await chooseAndMove(page, "No campaign");

    await expect(page.getByTestId("campaign-totals")).toContainText("1 program,");
    await expect(programs.locator("li")).toHaveCount(1);
    await expect(programs.locator(`[data-chat-id="${staying.id}"]`)).toBeVisible();
    await expect(programs.locator(`[data-chat-id="${leaving.id}"]`)).toHaveCount(0);
    await expect(page.getByTestId("campaign-new-program")).toBeFocused();
    expect(await campaignOf(page, leaving.id)).toBeNull();
    expect(await campaignOf(page, staying.id)).toBe(campaign.id);
  });

  test("is told the goal as it is changed from the next message it answers, and not before", async ({ page }) => {
    const campaign = await makeCampaign(page, "Rewritten", `The first goal, ${tag()}.`);
    const program = await makeProgram(page, "Told again", campaign.id);
    await page.goto(`/chat?id=${program.id}`);

    await message(page).fill("campaign: first");
    await page.getByRole("button", { name: "Send" }).click();
    await answered(page, `Given campaign ${campaign.name}: ${campaign.brief}`);

    const renamed = `Rewritten again ${tag()}`;
    const goal = `The second goal, ${tag()}.`;
    await page.goto(`/campaign?id=${campaign.id}`);
    await page.getByTestId("campaign-edit").click();
    await expect(dialog(page).getByRole("textbox", { name: "Name" })).toHaveValue(campaign.name);
    await expect(dialog(page).getByRole("textbox", { name: "Goal" })).toHaveValue(campaign.brief);
    await dialog(page).getByRole("textbox", { name: "Name" }).fill(renamed);
    await dialog(page).getByRole("textbox", { name: "Goal" }).fill(goal);
    await dialog(page).getByTestId("campaign-save").click();
    await expect(dialog(page)).toHaveCount(0);
    await expect(page.getByTestId("campaign-title")).toHaveText(renamed);
    await expect(page.getByTestId("campaign-brief")).toHaveText(goal);
    await expect(group(page, campaign.id).getByRole("link", { name: renamed })).toBeVisible();

    await page.getByRole("list", { name: "Programs of the campaign" }).getByRole("link", { name: new RegExp(program.title) }).click();
    await page.waitForURL(/\/chat\?id=/);
    await expect(page.getByTestId("lead-message")).toHaveCount(1);
    await message(page).fill("campaign: second");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByTestId("lead-message")).toHaveCount(2);
    await answered(page, `Given campaign ${renamed}: ${goal}`);
  });

  test("is told nothing of a campaign that has no goal written", async ({ page }) => {
    const campaign = await makeCampaign(page, "Without a goal");
    const program = await makeProgram(page, "Untold", campaign.id);
    await page.goto(`/campaign?id=${campaign.id}`);
    await expect(page.getByTestId("campaign-brief-empty")).toContainText("No goal is written");
    await expect(page.getByTestId("campaign-brief")).toHaveCount(0);

    await page.goto(`/chat?id=${program.id}`);
    await message(page).fill("campaign: told?");
    await page.getByRole("button", { name: "Send" }).click();
    await answered(page, "Given no campaign");
  });
});

test.describe("the list of programs on the side", () => {
  test("has a campaign's programs under it, which can be hidden and shown again, and the others after", async ({ page }) => {
    const campaign = await makeCampaign(page, "Folded");
    const inside = await makeProgram(page, "Inside", campaign.id);
    const outside = await makeProgram(page, "Outside");
    await page.goto("/");
    await expect(row(page, inside.id)).toBeVisible();

    const toggle = group(page, campaign.id).getByRole("button", { name: `Hide the programs of ${campaign.name}` });
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await toggle.click();
    await expect(row(page, inside.id)).toHaveCount(0);
    const shown = group(page, campaign.id).getByRole("button", { name: `Show the programs of ${campaign.name}` });
    await expect(shown).toHaveAttribute("aria-expanded", "false");
    await expect(group(page, campaign.id).getByRole("link", { name: campaign.name })).toContainText("1");
    await expect(row(page, outside.id)).toBeVisible();

    await shown.click();
    await expect(row(page, inside.id)).toBeVisible();

    // The campaigns are above the programs that are one of none
    const places = await page.evaluate(
      ([campaignId, programId]) => {
        const top = (selector: string) => document.querySelector(selector)?.getBoundingClientRect().top ?? Number.NaN;

        return [top(`[data-campaign-id="${campaignId}"]`), top(`nav[aria-label="Programs"] [data-chat-id="${programId}"]`)];
      },
      [campaign.id, outside.id],
    );
    expect(places[0]).toBeLessThan(places[1]);
  });

  test("leads to a campaign's page by its name", async ({ page }) => {
    const campaign = await makeCampaign(page, "Opened", `A goal to read, ${tag()}.`);
    await page.goto("/");

    await group(page, campaign.id).getByRole("link", { name: campaign.name }).click();
    await page.waitForURL(/\/campaign\?id=/);
    await expect(page.getByTestId("campaign-title")).toHaveText(campaign.name);
    await expect(page.getByTestId("campaign-brief")).toHaveText(campaign.brief);
    await expect(page).toHaveTitle(`${campaign.name} · Lumi Virtual Lab`);

    // Next writes the title again as a page opens, and for a campaign that is already known that can be after it was set here
    await page.evaluate(() => {
      document.title = "Lumi Virtual Lab";
    });
    await expect(page).toHaveTitle(`${campaign.name} · Lumi Virtual Lab`);

    await page.getByRole("link", { name: "New program", exact: true }).click();
    await expect(page.getByRole("heading", { name: HOME_HEADING })).toBeVisible();
    await expect(page).toHaveTitle("Lumi Virtual Lab");
  });
});

test.describe("deleting a campaign", () => {
  test("keeps its programs, which are then part of none", async ({ page }) => {
    const campaign = await makeCampaign(page, "Doomed", "A goal that goes.");
    const program = await makeProgram(page, "Survivor", campaign.id);
    await page.goto(`/campaign?id=${campaign.id}`);

    await page.getByTestId("campaign-delete").click();
    const sure = page.getByRole("alertdialog");
    await expect(sure).toContainText("Its 1 program is kept");
    await sure.getByRole("button", { name: "Keep it" }).click();
    await expect(sure).toHaveCount(0);
    expect((await page.request.get(`/api/campaigns/${campaign.id}`)).status()).toBe(200);

    await page.getByTestId("campaign-delete").click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();
    await page.waitForURL(/\/$/);

    expect((await page.request.get(`/api/campaigns/${campaign.id}`)).status()).toBe(404);
    expect(await campaignOf(page, program.id)).toBeNull();
    expect((await infoOf(page, program.id)).config.campaign).toBe("");
    await expect(group(page, campaign.id)).toHaveCount(0);
    await expect(row(page, program.id)).toBeVisible();
  });

  test("is not told of a campaign that is deleted while it is open, from the next message it answers", async ({ page }) => {
    const campaign = await makeCampaign(page, "Withdrawn", `Soon gone, ${tag()}.`);
    const program = await makeProgram(page, "Open meanwhile", campaign.id);
    await page.goto(`/chat?id=${program.id}`);
    await message(page).fill("campaign: before");
    await page.getByRole("button", { name: "Send" }).click();
    await answered(page, `Given campaign ${campaign.name}: ${campaign.brief}`);

    expect((await page.request.delete(`/api/campaigns/${campaign.id}`)).status()).toBe(204);
    await message(page).fill("campaign: after");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByTestId("lead-message")).toHaveCount(2);
    await answered(page, "Given no campaign");
  });
});

test.describe("a campaign that is not there", () => {
  test("is said not to be, from its address, with the way to begin a program", async ({ page }) => {
    await page.goto("/campaign?id=not-a-campaign");
    await expect(page.getByRole("heading", { name: "This campaign is not here" })).toBeVisible();
    await page.getByRole("link", { name: "Start a program" }).click();
    await expect(page).toHaveURL(/\/$/);
  });
});

test.describe("what is shown of campaigns", () => {
  test("is without anything wrong for someone who cannot see it", async ({ page }) => {
    const campaign = await makeCampaign(page, "Seen", `A goal that is seen, ${tag()}.`);
    const program = await makeProgram(page, "Seen program", campaign.id);
    await makeProgram(page, "Seen alone");

    await page.goto("/");
    await expect(page.getByRole("combobox", { name: "Campaign" })).toBeVisible();
    expect(await accessibilityProblems(page, ["heading-order"])).toEqual([]);

    await page.goto(`/campaign?id=${campaign.id}`);
    await expect(page.getByTestId("campaign-brief")).toBeVisible();
    await expect(page.getByTestId("campaign-totals")).toContainText("1 program");
    expect(await accessibilityProblems(page, ["heading-order", "page-has-heading-one"])).toEqual([]);

    await page.getByTestId("campaign-edit").click();
    await expect(dialog(page)).toBeVisible();
    await expect(dialog(page)).toHaveCSS("opacity", "1");
    expect(await accessibilityProblems(page, ["heading-order", "aria-hidden-focus", "region", "page-has-heading-one"])).toEqual([]);
    await dialog(page).getByRole("textbox", { name: "Name" }).fill("");
    await dialog(page).getByTestId("campaign-save").click();
    await expect(dialog(page).getByText("A campaign needs a name.")).toBeVisible();
    expect(await accessibilityProblems(page, ["heading-order", "aria-hidden-focus", "region", "page-has-heading-one"])).toEqual([]);
    await page.keyboard.press("Escape");
    await expect(dialog(page)).toHaveCount(0);

    await page.goto(`/chat?id=${program.id}`);
    await page.getByTestId("program-campaign-button").click();
    await expect(mover(page)).toBeVisible();
    await expect(mover(page)).toHaveCSS("opacity", "1");
    expect(await accessibilityProblems(page, ["heading-order", "aria-hidden-focus", "region", "page-has-heading-one"])).toEqual([]);
  });
});
