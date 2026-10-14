import { calling, lead, tell, user, type Told } from "./replay";
import { expect, test } from "./fixtures";

// What the page shows for events that the scripted lead does not tell of, such as a turn that was cut short and the
// notes a researcher leaves: the conversation is real, and the events it is told of are written here

test.describe("events as the server tells of them", () => {
  test("a call that was cut short before it answered is said to be, with the code it was to run", async ({ page }) => {
    await tell(page, [
      user("Run it"),
      calling("c1", "run_code", { code: "import time\ntime.sleep(60)" }),
      { kind: "stopped", text: "Stopped by you. What was done is kept." },
    ]);

    const call = page.getByTestId("call");
    await expect(call).toHaveAttribute("data-status", "interrupted");
    await expect(call).toContainText("Cut short");
    await expect(call.getByTestId("code-cell")).toContainText("time.sleep(60)");
    await expect(call.getByTestId("code-cell")).toHaveAttribute("data-status", "unknown");
    await expect(call.getByRole("status")).toHaveCount(0);
    await expect(page.getByRole("status").filter({ hasText: /stopped/i })).toBeVisible();
  });

  test("a call that is running, and has not answered, says so while the turn goes on", async ({ page }) => {
    await tell(page, [user("Run it"), calling("c1", "run_code", { code: "wait()" }), { kind: "status", turn: 0, data: { state: "running" } }]);

    const call = page.getByTestId("call");
    await expect(call).toHaveAttribute("data-status", "running");
    await expect(call.getByTestId("code-cell")).toHaveAttribute("data-status", "running");
    await expect(call.getByRole("status").first()).toContainText("Working");
    await expect(call.getByTestId("code-cell").getByRole("status")).toContainText("Running");
    await expect(page.getByText("Thinking…")).toHaveCount(0);
  });

  test("a turn that has shown nothing yet says the lead is thinking, until it shows something", async ({ page }) => {
    await tell(page, [user("Think"), { kind: "status", turn: 0, data: { state: "running" } }]);

    await expect(page.getByText("Thinking…")).toBeVisible();
    await expect(page.getByTestId("lead-block")).toBeVisible();
  });

  test("a tool that has not answered says so when it is opened, and its words are shown as they came", async ({ page }) => {
    await tell(page, [
      user("Call"),
      { kind: "tool_calls", speaker: lead, text: "", data: { calls: [{ id: "m1", name: "mystery", arguments: "not json at all" }] } },
      { kind: "status", turn: 0, data: { state: "running" } },
    ]);

    const call = page.getByTestId("call");
    await expect(call).toContainText("Calling mystery");
    await call.locator("summary").click();
    await expect(call.getByText("Asked", { exact: true })).toBeVisible();
    await expect(call).toContainText("not json at all");
    await expect(call).toContainText("Nothing has come back yet.");
  });

  test("what code that did not finish well, or gave a value, is shown as", async ({ page }) => {
    const cell = (call: string, data: Record<string, unknown>): Told => ({
      kind: "cell",
      data: { call, code: "work()", language: "python", output: "", duration: 30, plots: [], produced_files: [], ...data },
    });
    await tell(page, [
      user("Run"),
      calling("a", "run_code", { code: "work()" }),
      cell("a", { status: "timeout" }),
      calling("b", "run_code", { code: "work()" }),
      cell("b", { status: "lost" }),
      calling("c", "run_code", { code: "work()" }),
      cell("c", { status: "ok", value: { genes: 3 }, duration: 75 }),
      { kind: "answer", speaker: lead, text: "Done." },
    ]);

    const cells = page.getByTestId("code-cell");
    await expect(cells).toHaveCount(3);
    await expect(cells.nth(0)).toContainText("Stopped at its time limit (30 s)");
    await expect(cells.nth(1)).toContainText("The session ended while it ran");
    await expect(cells.nth(2)).toContainText("Ran in 1 min 15 s");
    await expect(cells.nth(2).getByRole("group", { name: "Value" })).toContainText('"genes": 3');
    await expect(cells.nth(0).getByRole("group", { name: "Value" })).toHaveCount(0);
  });

  test("notes left for the lead are shown with whether they were read", async ({ page }) => {
    await tell(page, [
      user("Start"),
      { kind: "note", speaker: "Human researcher", text: "Use the 2024 data", data: { to: "lead", read: true } },
      { kind: "note", speaker: "Human researcher", text: "Ask the team too", data: { to: "lab", read: true } },
      { kind: "note", speaker: "Human researcher", text: "This came too late", data: { to: null, read: false } },
      { kind: "note", speaker: "Human researcher", text: "This was not read either", data: { to: "lead", read: false } },
      { kind: "answer", speaker: lead, text: "Done." },
    ]);

    const notes = page.getByTestId("note");
    await expect(notes).toHaveCount(4);
    await expect(notes.nth(3)).toContainText("Not read: it came too late");
    await expect(notes.nth(0)).toContainText("Use the 2024 data");
    await expect(notes.nth(0)).toContainText("Read by the lead");
    await expect(notes.nth(1)).toContainText("Read by the team");
    await expect(notes.nth(2)).toContainText("Not read: it came too late");
  });

  test("files named outside the conversation's files are not linked to, and a name with a percent sign is", async ({ page }) => {
    const asked: string[] = [];
    page.on("request", (request) => {
      if (request.url().includes("/files/") || request.url().includes("health.png")) asked.push(request.url());
    });
    await tell(page, [
      user("Files"),
      calling("c1", "run_code", { code: "work()" }),
      {
        kind: "cell",
        data: {
          call: "c1",
          code: "work()",
          status: "ok",
          plots: ["../../health.png", "plots/ok.png"],
          produced_files: ["../../health.png", "/etc/passwd", "100%.csv", "my results/a#b.csv"],
        },
      },
      { kind: "answer", speaker: lead, text: "Done." },
    ]);

    const cell = page.getByTestId("code-cell");
    // The figure that is inside the files is asked for, and is not there, as the conversation has no such file
    const figures = cell.getByRole("group", { name: "Figures" });
    await expect(figures).toContainText("../../health.png is not available");
    await expect(figures).toContainText("plots/ok.png is not available");
    expect(asked.filter((url) => url.endsWith("/files/plots/ok.png"))).toHaveLength(1);
    expect(asked.some((url) => url.includes("health.png") || url.includes(".."))).toBe(false);
    // A figure is not listed again as a file, and of the three that are, the one that is not inside the files is not a link
    const made = cell.getByRole("list", { name: "Files it made" });
    await expect(made.getByRole("listitem")).toHaveText(["/etc/passwd", "100%.csv", "my results/a#b.csv"]);
    const links = made.getByRole("link");
    await expect(links).toHaveCount(2);
    const hrefs = await links.evaluateAll((all) => all.map((link) => link.getAttribute("href")));
    expect(hrefs.filter((href) => href?.endsWith("/files/100%25.csv"))).toHaveLength(1);
    expect(hrefs.filter((href) => href?.endsWith("/files/my%20results/a%23b.csv"))).toHaveLength(1);
  });

  test("events that are not as they should be are left out, and what is as it should be is shown", async ({ page }) => {
    await tell(page, [
      user("Odd things"),
      { kind: "something_new", text: "A kind this page does not know" },
      { kind: "tool_calls", speaker: lead, text: "A call with nothing in it.", data: { calls: "not a list" } },
      { kind: "cell", data: { call: "nothing-by-that-name", code: "x", output: 5 } },
      calling("c1", "run_code", { code: "print(1)" }),
      { kind: "cell", data: { call: "c1", code: "print(1)", status: "ok", output: 7, duration: "slow", plots: "no", produced_files: [1, "kept.txt"] } },
      { kind: "tool_output", text: "1", data: { call: "c1", name: "run_code" } },
      { kind: "answer", speaker: lead, text: "Still here." },
    ]);

    await expect(page.getByTestId("lead-message")).toContainText("Still here.");
    await expect(page.getByTestId("call")).toHaveCount(1);
    await expect(page.getByTestId("code-cell")).toHaveCount(1);
    await expect(page.getByTestId("code-cell")).toContainText("print(1)");
    await expect(page.getByTestId("code-cell").getByRole("list", { name: "Files it made" }).getByRole("listitem")).toHaveText(["kept.txt"]);
    await expect(page.getByText("A kind this page does not know")).toHaveCount(0);
  });
});
