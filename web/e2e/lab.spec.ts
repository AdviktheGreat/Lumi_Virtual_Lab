import type { Page } from "@playwright/test";
import { answered, ask, askWhereCodeRuns, expect, test } from "./fixtures";

const call = (page: Page) => page.getByTestId("call");
const lab = (page: Page) => page.getByTestId("lab");
const turns = (page: Page) => lab(page).getByTestId("lab-turn");
const speakers = (page: Page) => turns(page).evaluateAll((found) => found.map((turn) => turn.getAttribute("data-speaker")));

interface Told {
  kind: string;
  speaker?: string | null;
  text?: string;
  data?: Record<string, unknown>;
}

const LEAD = "Principal Investigator";
const labEvent = (event: string, fields: { speaker?: string; text?: string; round?: number | null; details?: Record<string, unknown> } = {}): Told => ({
  kind: "lab",
  speaker: fields.speaker ?? null,
  text: fields.text ?? "",
  data: { call: "t1", event, meeting: "lab_001", round: fields.round ?? null, details: fields.details ?? {} },
});

// A team's session as the server tells of it, from the call that brings the team in to the lead's answer
const SESSION: Told[] = [
  { kind: "user", speaker: "Human researcher", text: "Bring the team in", data: { attachments: [] } },
  { kind: "tool_calls", speaker: LEAD, text: "", data: { calls: [{ id: "t1", name: "convene_team", arguments: '{"agenda":"Design a nanobody."}' }] } },
  labEvent("started", { details: { meeting_type: "team", agenda: "Design a nanobody.", num_rounds: 1, team: [{ title: LEAD }, { title: "Immunologist" }] } }),
  labEvent("turn", { speaker: LEAD, round: 1 }),
  labEvent("message", { speaker: LEAD, text: "Let us begin.", round: 1, details: { kind: "response" } }),
  labEvent("finished", { text: "The summary." }),
  { kind: "tool_output", text: "The team agreed.", data: { call: "t1" } },
  { kind: "answer", speaker: LEAD, text: "That is done." },
];

// Opens a conversation whose events come one each time the page asks for them, a moment apart, so that every step of a
// session is seen while it is told. The conversation says it had `known` events when the page was opened, which is
// what a conversation that is over says of all of them, and one that is only beginning says of none.
async function told(page: Page, title: string, known: number): Promise<void> {
  const made = await page.request.post("/api/chats", { data: { title } });
  expect(made.status()).toBe(201);
  const id: string = (await made.json()).id;
  let asked = 0;
  await page.route("**/api/chats/*/events*", (route) => {
    const at = asked;
    asked += 1;
    const event = SESSION[at];

    return route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream", "cache-control": "no-cache" },
      body: `retry: ${event === undefined ? 600_000 : 100}\n\n${
        event === undefined ? "" : `event: chat\nid: ${at + 1}\ndata: ${JSON.stringify({ id: at + 1, turn: 1, speaker: null, text: "", data: {}, time: 0, ...event })}\n\n`
      }`,
    });
  });
  await page.route(`**/api/chats/${id}`, async (route) => {
    const response = await route.fetch();
    const info = await response.json();
    await route.fulfill({ response, json: { ...info, last_event_id: known } });
  });
  await page.goto(`/chat?id=${id}`);
}

test.describe("a team the lead brings in", () => {
  test("a discussion is shown in the call that brought the team in: who is in it, and who said what in each round", async ({ page }) => {
    await ask(page, "lab:team please");
    await answered(page, "That is done: 1 step ran.", 30_000);

    await expect(call(page)).toHaveCount(1);
    await expect(call(page)).toContainText("Convened the team");
    await expect(call(page)).toHaveAttribute("data-status", "done");
    await expect(lab(page)).toHaveAttribute("data-status", "finished");
    await expect(lab(page)).toContainText("Team discussion");
    await expect(lab(page)).toContainText("1 round");

    const team = lab(page).getByRole("list", { name: "Team" }).getByRole("listitem");
    await expect(team).toHaveText([/Principal Investigator/, /Immunologist/, /Scientific Critic/]);

    const round = lab(page).getByRole("region", { name: "Round 1" });
    await expect(round.getByTestId("lab-turn")).toHaveCount(3);
    expect(await speakers(page)).toEqual(["Principal Investigator", "Immunologist", "Scientific Critic", "Principal Investigator"]);
    await expect(round).toContainText("Let us begin: which part of TP53 should a nanobody bind?");
    await expect(round.getByTestId("lab-turn").nth(1)).toContainText("As the Immunologist, I would target the conserved DNA-binding epitope.");
    await expect(round.getByTestId("lab-turn").nth(2)).toContainText("As the Scientific Critic, I ask what shows that the epitope is exposed.");

    // The lead's summing up is the last round, which has its own name
    const summing = lab(page).getByRole("region", { name: "Summary" });
    await expect(summing.getByTestId("lab-turn")).toHaveCount(1);
    await expect(summing).toContainText("Summary: target the conserved DNA-binding epitope, and check that it is exposed.");
    // What the call gave back is with the call, after what the team said
    await expect(call(page)).toContainText("took part in a discussion that you led");
  });

  test("what the session was for is there to be opened, and is not in the way", async ({ page }) => {
    await ask(page, "lab:team the agenda");
    await answered(page, "That is done: 1 step ran.", 30_000);

    const agenda = lab(page).getByTestId("lab-agenda");
    const what = agenda.getByText("Design a nanobody against TP53.");
    await expect(agenda.getByText("Agenda")).toBeVisible();
    await expect(what).toBeHidden();

    await agenda.getByText("Agenda").click();
    await expect(what).toBeVisible();

    await agenda.getByText("Agenda").click();
    await expect(what).toBeHidden();
  });

  test("one scientist, reviewed by the critic, ends with their final answer", async ({ page }) => {
    await ask(page, "lab:consult please");
    await answered(page, "That is done: 1 step ran.", 30_000);

    await expect(call(page)).toContainText("Consulted Immunologist");
    await expect(lab(page)).toContainText("One scientist, reviewed by the critic");
    expect(await speakers(page)).toEqual(["Immunologist", "Scientific Critic", "Immunologist"]);
    await expect(lab(page).getByRole("region", { name: "Round 1" })).toBeVisible();
    await expect(lab(page).getByRole("region", { name: "Final answer" })).toContainText("I would target the conserved DNA-binding epitope.");
  });

  test("a session that was over before the page was opened is closed, and is the same once it is opened", async ({ page }) => {
    await ask(page, "lab:team after a reload");
    await answered(page, "That is done: 1 step ran.", 30_000);
    const first = await speakers(page);

    await page.reload();
    await expect(call(page)).toHaveAttribute("data-status", "done");

    await expect(lab(page)).toBeHidden();
    await call(page).getByText("Convened the team").click();
    await expect(lab(page)).toBeVisible();
    expect(await speakers(page)).toEqual(first);
    await expect(lab(page)).toHaveAttribute("data-status", "finished");
  });

  test("a session that was over before the page was opened is not opened while the past is told to the page, a piece at a time", async ({ page }) => {
    await told(page, "Lab: a past told in pieces", SESSION.length);

    await expect(call(page)).toBeVisible();
    // The call is going on for as long as its end has not been told, and is not shown open for that
    await expect(call(page)).toHaveAttribute("data-status", "running");
    await expect(lab(page)).toBeHidden();
    await expect(page.getByTestId("lead-message").last()).toContainText("That is done.", { timeout: 15_000 });

    await expect(call(page)).toHaveAttribute("data-status", "done");
    await expect(lab(page)).toBeHidden();
    await call(page).getByText("Convened the team").click();
    await expect(lab(page)).toHaveAttribute("data-status", "finished");
  });

  test("a session that goes on as the page is open is shown open, and is left open when it ends", async ({ page }) => {
    await told(page, "Lab: a session as it happens", 0);

    await expect(call(page)).toHaveAttribute("data-status", "running");
    await expect(lab(page)).toBeVisible();
    await expect(page.getByTestId("lead-message").last()).toContainText("That is done.", { timeout: 15_000 });

    await expect(call(page)).toHaveAttribute("data-status", "done");
    await expect(lab(page)).toHaveAttribute("data-status", "finished");
    await expect(lab(page)).toBeVisible();
  });

  test("the session is open while the team works, and shows what a scientist is writing as they write it", async ({ page }) => {
    await ask(page, "lab:slow please");

    await expect(call(page)).toHaveAttribute("data-status", "running");
    await expect(lab(page)).toBeVisible();
    await expect(lab(page)).toHaveAttribute("data-status", "running");
    const writing = page.getByTestId("lab-writing");
    await expect(writing).toContainText("point1", { timeout: 15_000 });
    // It is in the turn of the one who writes it
    await expect(turns(page).last().getByTestId("lab-writing")).toBeVisible();
    await expect(turns(page).last()).toHaveAttribute("data-speaker", "Immunologist");

    await answered(page, "That is done: 1 step ran.", 45_000);

    // What was written is the reply, which is where it was, and nothing is still being written
    await expect(writing).toHaveCount(0);
    await expect(lab(page)).toHaveAttribute("data-status", "finished");
    await expect(page.getByTestId("lab-reply").filter({ hasText: "point120" })).toHaveCount(1);
    // It stays open, since it was open to be read
    await expect(lab(page)).toBeVisible();
  });

  test("what is open or closed is left as the researcher left it, when the session ends", async ({ page }) => {
    await ask(page, "lab:slow and closed");
    await expect(lab(page)).toBeVisible();

    await call(page).getByText("Convening the team").click();
    await expect(lab(page)).toBeHidden();

    await answered(page, "That is done: 1 step ran.", 45_000);
    await expect(call(page)).toHaveAttribute("data-status", "done");
    await expect(lab(page)).toBeHidden();
  });

  test("stopping the lead while the team works cuts the session short, and is not shown as an error", async ({ page }) => {
    await ask(page, "lab:slow and stopped");
    await expect(page.getByTestId("lab-writing")).toContainText("point1", { timeout: 15_000 });

    await page.getByRole("button", { name: "Stop" }).click();

    await expect(page.getByTestId("chat-state")).toHaveCount(0, { timeout: 30_000 });
    await expect(lab(page)).toHaveAttribute("data-status", "interrupted");
    await expect(lab(page)).toContainText("The session was cut short.");
    await expect(lab(page).getByRole("alert")).toHaveCount(0);
    await expect(page.getByTestId("lab-writing")).toHaveCount(0);
    // The call did give back what it knew, which is that there is no summary
    await expect(call(page)).toContainText("stopped the team before it finished");
  });

  test("code a scientist runs is shown in their turn, with what it printed and the files it made", async ({ page }) => {
    await askWhereCodeRuns(page, "lab:code please");
    await answered(page, "That is done: 1 step ran.", 30_000);

    const immunologist = turns(page).and(page.locator('[data-speaker="Immunologist"]'));
    await expect(immunologist).toHaveCount(1);
    await expect(immunologist).toContainText("Let me check that.");
    const cell = immunologist.getByTestId("code-cell");
    await expect(cell).toHaveCount(1);
    await expect(cell).toHaveAttribute("data-status", "ok");
    await expect(cell).toContainText('open("lab_notes.txt", "w")');
    await expect(cell.getByTestId("code-output")).toContainText("lab code ran");
    await expect(cell.getByRole("list", { name: "Files it made" })).toContainText("lab_notes.txt");
    // The call to run the code is what the run shows, so it is not listed as well, and the reply is after it
    await expect(lab(page).getByTestId("lab-tool")).toHaveCount(0);
    await expect(immunologist).toContainText("As the Immunologist, I would target the conserved DNA-binding epitope.");
    // The team's code is the conversation's own, so what it made is in its files
    await expect(page.getByTestId("files-count")).toHaveText("1");
  });
});
