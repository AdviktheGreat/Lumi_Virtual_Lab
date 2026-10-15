import type { Locator, Page } from "@playwright/test";
import { accessibilityProblems, pastTheEdge } from "./axe";
import { answered, ask, askWhereCodeRuns, expect, HOME_HEADING, test } from "./fixtures";
import { approval, asked, calling, connection, ended, lead, ORDER_FIELDS, tell, user, type Told } from "./replay";

const SIZES = [
  { name: "desktop", width: 1280, height: 800 },
  { name: "phone", width: 390, height: 844 },
];

// What is not looked at when a menu is open: the page behind it is hidden from what reads the page, as it should be, while
// what is on it cannot be reached, which axe cannot tell, and what the menu is made of is not in a part of the page. And
// what a model writes in Markdown starts at any level of heading, which is not for the page to put right.
const MODEL_WRITES = ["heading-order"];
const MENU_OPEN = [...MODEL_WRITES, "aria-hidden-focus", "region", "page-has-heading-one"];

async function themed(page: Page, theme: "light" | "dark", size: { width: number; height: number }): Promise<void> {
  await page.setViewportSize({ width: size.width, height: size.height });
  await page.evaluate((chosen) => localStorage.setItem("vl-theme", chosen), theme);
  await page.reload();
  await expect(page.getByRole("heading", { name: HOME_HEADING })).toBeVisible();
  await expect(page.locator("html")).toHaveClass(theme === "dark" ? /dark/ : /^(?!.*dark)/);
}

async function looksRight(page: Page, state: string, skip: string[] = MODEL_WRITES): Promise<void> {
  expect.soft(await accessibilityProblems(page, skip), `${state}: what is wrong for someone who cannot see it or use a mouse`).toEqual([]);
  expect.soft(await pastTheEdge(page), `${state}: how far the page goes past its edge`).toBeLessThanOrEqual(0);
}

for (const theme of ["light", "dark"] as const) {
  for (const size of SIZES) {
    test.describe(`${theme} theme, ${size.name}`, () => {
      test("the pages and what opens on them have nothing wrong for someone who cannot see them or use a mouse, and fit the window", async ({
        page,
      }) => {
        test.setTimeout(180_000);
        await themed(page, theme, size);
        await looksRight(page, "the home page");

        await ask(page, "markdown: show me what you can do");
        await answered(page, /./);
        await looksRight(page, "a reply written in Markdown");

        await page.goto("/");
        await ask(page, "wide: show me what does not fit");
        await answered(page, /./, 20_000);
        await looksRight(page, "a reply with a table and lines of code wider than the page");

        await page.goto("/");
        await ask(page, "tool:resources find what suits it");
        await answered(page, /./, 20_000);
        await page.getByTestId("call").locator("summary").click();
        await looksRight(page, "a tool's call, opened");

        await askWhereCodeRuns(page, "code:plot draw something");
        await answered(page, /./, 20_000);
        await looksRight(page, "code that drew a figure");

        await askWhereCodeRuns(page, "code:files write some files");
        await answered(page, /./, 30_000);
        await page.getByTestId("files-toggle").click();
        await expect(page.getByTestId("files-panel")).toBeVisible();
        await looksRight(page, "the files that were made");
        for (const [path, shown] of [
          ["tables/wide.tsv", "file-table"],
          ["logs/big.log", "file-text"],
        ]) {
          await page.locator(`[data-testid="file-row"][data-path="${path}"]`).click();
          await expect(page.getByTestId(shown)).toBeVisible();
          await looksRight(page, `${path}, shown`);
          await page.getByRole("button", { name: "Back to the files" }).click();
        }
        await page.getByRole("button", { name: "Close the files" }).click();

        await page.goto("/");
        await ask(page, "lab:team convene a discussion");
        await answered(page, /./, 20_000);
        await looksRight(page, "a team's session");

        await page.goto("/");
        await ask(page, "fail: this will go wrong");
        await expect(page.getByRole("alert").filter({ hasText: "scripted model failed" })).toBeVisible();
        await looksRight(page, "a turn that ended in an error");

        await page.getByTestId("export-toggle").click();
        await expect(page.getByTestId("export-html")).toBeVisible();
        // Once it has faded in, since the text of what is still fading has less contrast than it will
        await expect(page.getByRole("menu")).toHaveCSS("opacity", "1");
        await looksRight(page, "the Save menu", MENU_OPEN);
        await page.keyboard.press("Escape");
        await expect(page.getByRole("menu")).toHaveCount(0);

        await page.getByTestId("files-toggle").click();
        await expect(page.getByTestId("files-panel")).toBeVisible();
        await looksRight(page, "the files");
        await page.getByRole("button", { name: "Close the files" }).click();

        if (size.name === "phone") {
          await page.getByRole("button", { name: "Show the conversations" }).click();
          await expect(page.getByRole("navigation", { name: "Conversations" })).toBeVisible();
          await looksRight(page, "the conversations");
        }

        await page.getByRole("button", { name: "Settings" }).first().click();
        await expect(page.getByRole("dialog", { name: "Settings" })).toHaveCSS("opacity", "1");
        for (const tab of ["Model", "Keys", "Code", "Scientists", "Tools"]) {
          await page.getByRole("tab", { name: tab }).click();
          await expect(page.getByRole("tab", { name: tab })).toHaveAttribute("aria-selected", "true");
          await looksRight(page, `the ${tab} settings`);
        }
        await page.keyboard.press("Escape");
        await expect(page.getByRole("dialog")).toHaveCount(0);

        await page.getByRole("button", { name: "Set up" }).first().click();
        await expect(page.getByRole("dialog", { name: "Set up" })).toHaveCSS("opacity", "1");
        for (const tab of ["Overview", "Data lake", "Jobs"]) {
          await page.getByRole("tab", { name: tab }).click();
          await expect(page.getByRole("tab", { name: tab })).toHaveAttribute("aria-selected", "true");
          await looksRight(page, `the ${tab} part of the setup`);
        }
      });

      test("what a conversation asks of the researcher, and the servers it is connected to, have nothing wrong and fit the window", async ({
        page,
      }) => {
        await themed(page, theme, size);
        const running: Told = { kind: "status", turn: 0, data: { state: "running" } };
        await tell(page, [
          user("Order it, and say what the echo gives"),
          connection("connecting"),
          connection("ready", { tools: 12 }),
          connection("connecting", { server: "vault", title: "Vault" }),
          connection("signing_in", { server: "vault", title: "Vault", url: "https://sign.example.org/authorize?client=a-long-address&state=" + "x".repeat(120) }),
          connection("connecting", { server: "gone", title: "Gone" }),
          connection("failed", { server: "gone", title: "Gone" }, "The server did not answer within 30 seconds, which is long enough to wrap on a narrow window."),
          calling("c1", "genes_echo", { text: "ab" }),
          approval("waiting", "a"),
          approval("approved", "a"),
          approval("waiting", "b"),
          approval("declined", "b"),
          approval("waiting", "c"),
          approval("withdrawn", "d"),
          asked({ request: "q0", text: "Go ahead?" }),
          ended("answered", "q0"),
          asked({ request: "q1", fields: ORDER_FIELDS, required: ["name", "kind"] }),
          running,
        ]);
        await expect(page.getByTestId("question").filter({ has: page.getByLabel("Sample name") })).toBeVisible();
        await looksRight(page, "the cards of calls to allow, of questions, and of connections");

        await page.getByTestId("question").getByRole("button", { name: "Send" }).click();
        await expect(page.getByText("Sample name must be filled in")).toBeVisible();
        await looksRight(page, "a question that was sent with what must be filled in left out");

        await tell(page, [
          user("Pay for it"),
          asked({ request: "q2", url: "https://pay.example.org/a/long/address/for/the/page/that/is/asked/for/" + "y".repeat(80), text: "Pay for the test at this page." }),
          running,
        ]);
        await expect(page.getByTestId("question")).toBeVisible();
        await looksRight(page, "a question that asks the researcher to go to a page");
      });

      test("what the settings show of a server that was checked, and is signed in to, has nothing wrong and fits the window", async ({
        page,
      }) => {
        await themed(page, theme, size);
        await page.route("**/api/mcp", async (route) => {
          const response = await route.fetch();
          const body = await response.json();
          body.servers = body.servers.map((server: { name: string }) => (server.name === "proto_hosted" ? { ...server, signed_in: true } : server));
          await route.fulfill({ response, json: body });
        });
        let release: () => void = () => undefined;
        const held = new Promise<void>((resolve) => (release = resolve));
        let found: object = { ok: true, tools: Array.from({ length: 14 }, (_, at) => `proto_hosted_a_tool_with_a_long_name_${at}`), reason: null };
        await page.route("**/api/mcp/servers/proto_hosted/check", async (route) => {
          await held;
          await route.fulfill({ json: found });
        });
        if (size.name === "phone") await page.getByRole("button", { name: "Show the conversations" }).click();
        await page.getByRole("button", { name: "Settings" }).first().click();
        await expect(page.getByRole("dialog", { name: "Settings" })).toHaveCSS("opacity", "1");
        await page.getByRole("tab", { name: "Tools" }).click();
        const row = page.getByTestId("mcp-proto_hosted");
        await expect(row.getByRole("button", { name: "Sign out of Proto, hosted" })).toBeVisible();
        await looksRight(page, "a server that is signed in to");

        await row.getByRole("button", { name: "Check connection to Proto, hosted" }).click();
        await expect(row.getByRole("status").filter({ hasText: "Connecting…" })).toBeVisible();
        await looksRight(page, "a server being connected to, to be looked at");
        release();
        await expect(row.getByRole("status").filter({ hasText: "Connected." })).toBeVisible();
        await looksRight(page, "what a check of a server found");

        found = {
          ok: false,
          tools: [],
          reason: `Could not connect to the MCP server proto_hosted (at https://mcp.example.org/mcp): it did not answer within 30 seconds.\n${"x".repeat(150)}`,
        };
        await row.getByRole("button", { name: "Check connection to Proto, hosted" }).click();
        await expect(row.getByRole("alert").filter({ hasText: "Could not connect" })).toBeVisible();
        await looksRight(page, "why a check of a server found it could not be connected to");
      });
    });
  }
}

test.describe("what is shown while something is being got", () => {
  test("is a page of its own, with a main part, while the server is looked for", async ({ page }) => {
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/api/health", async (route) => {
      await held;

      return route.continue().catch(() => undefined);
    });

    await page.goto("/");
    await expect(page.getByRole("main")).toBeVisible();
    await expect(page.getByRole("main")).toHaveAttribute("aria-busy", "true");
    await looksRight(page, "the server being looked for");
    release();
    await expect(page.getByRole("heading", { name: HOME_HEADING })).toBeVisible();
    await expect(page.getByRole("main")).not.toHaveAttribute("aria-busy", "true");
  });

  test("is a status with a name, in the list, the conversation, the files, and a file, and has nothing wrong", async ({ page }) => {
    test.setTimeout(90_000);
    const id = await askWhereCodeRuns(page, "code:files while it loads");
    await answered(page, "That is done: 1 step ran.", 30_000);
    // A conversation with something in it is shown as soon as its events come, which are not held, so one without is what
    // shows that it is being got
    const made = await page.request.post("/api/chats", { data: { title: "Loading: nothing in it yet" } });
    expect(made.status()).toBe(201);
    const empty: string = (await made.json()).id;
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => (release = resolve));
    // Only what is got is held, so that what is changed by a test is not
    const hold = (pattern: string) =>
      page.route(pattern, async (route) => {
        if (route.request().method() !== "GET") return route.fallback();
        await held;

        return route.continue().catch(() => undefined);
      });
    await hold("**/api/chats");
    await hold("**/api/chats/*");
    let releaseList: () => void = () => undefined;
    const heldList = new Promise<void>((resolve) => (releaseList = resolve));
    await page.route("**/api/chats/*/files", async (route) => {
      await heldList;

      return route.continue().catch(() => undefined);
    });
    let releaseFile: () => void = () => undefined;
    const heldFile = new Promise<void>((resolve) => (releaseFile = resolve));
    await page.route("**/api/chats/*/files/**", async (route) => {
      await heldFile;

      return route.continue().catch(() => undefined);
    });

    await page.goto(`/chat?id=${empty}`);
    await expect(page.getByRole("status", { name: "Loading conversations" })).toBeVisible();
    await expect(page.getByRole("status", { name: "Loading the conversation" })).toBeVisible();
    await looksRight(page, "the list and the conversation, being got");
    release();

    await page.goto(`/chat?id=${id}`);
    await expect(page.getByTestId("files-toggle")).toBeEnabled();
    await page.getByTestId("files-toggle").click();
    await expect(page.getByRole("status", { name: "Loading the files" })).toBeVisible();
    await looksRight(page, "the files, being got");
    releaseList();

    await page.locator('[data-testid="file-row"][data-path="logs/big.log"]').click();
    await expect(page.getByRole("status", { name: "Loading the file" })).toBeVisible();
    await looksRight(page, "a file, being got");
    releaseFile();
    await expect(page.getByRole("status", { name: "Loading the file" })).toHaveCount(0);
  });
});

const LINES = Array.from({ length: 120 }, (_, number) => `line ${number + 1} of what it printed`).join("\n");
const lab = (event: string, fields: { speaker?: string; text?: string; details?: Record<string, unknown> } = {}): Told => ({
  kind: "lab",
  speaker: fields.speaker ?? null,
  text: fields.text ?? "",
  data: { call: "t1", event, meeting: "lab_001", round: null, details: fields.details ?? {} },
});

// Whether a box scrolls, and whether the keyboard can reach it
async function scrolling(box: Locator): Promise<{ scrolls: boolean; focusable: boolean }> {
  return box.evaluate((element) => ({
    scrolls: element.scrollHeight > element.clientHeight + 1 || element.scrollWidth > element.clientWidth + 1,
    focusable: element.getAttribute("tabindex") === "0",
  }));
}

test.describe("what scrolls can be reached from the keyboard", () => {
  test("what a tool gave back, code that gave a long value, and what a scientist's tools gave back are, where they are long", async ({
    page,
  }) => {
    const value = { genes: Array.from({ length: 60 }, (_, number) => `GENE${number}`) };
    await tell(page, [
      user("Show me what you did"),
      calling("c1", "run_code", { code: "work()" }),
      { kind: "tool_output", text: LINES, data: { call: "c1", name: "run_code" } },
      calling("c2", "mystery", { target: "TP53" }),
      { kind: "tool_output", text: LINES, data: { call: "c2", name: "mystery" } },
      calling("c3", "run_code", { code: "work()" }),
      {
        kind: "cell",
        data: { call: "c3", code: "work()", language: "python", output: "", duration: 3, plots: [], produced_files: [], status: "ok", value },
      },
      {
        kind: "tool_calls",
        speaker: lead,
        text: "",
        data: { calls: [{ id: "t1", name: "convene_team", arguments: '{"agenda":"Design a nanobody."}' }] },
      },
      lab("started", { details: { meeting_type: "team", agenda: "Design.", num_rounds: 1, team: [{ title: lead }] } }),
      lab("turn", { speaker: lead }),
      lab("tool_calls", { speaker: lead, text: "Looking it up.", details: { calls: [{ id: "s1", name: "look_up", arguments: "{}" }] } }),
      lab("message", { speaker: lead, text: LINES, details: { kind: "tool_output" } }),
      lab("finished", { text: "Done." }),
      { kind: "tool_output", text: "The team agreed.", data: { call: "t1" } },
      { kind: "answer", speaker: lead, text: "That is all." },
    ]);

    const reached = async (box: Locator) => expect.poll(() => scrolling(box)).toEqual({ scrolls: true, focusable: true });
    await reached(page.locator('[data-testid="call"][data-call="run_code"]').first().locator("pre.max-h-60"));
    await page.locator('[data-call="mystery"] summary').click();
    await reached(page.locator('[data-call="mystery"] div.max-h-96'));
    await reached(page.getByRole("group", { name: "Value" }));
    await page.locator('details[data-call="convene_team"] > summary').click();
    await page.getByText("What it gave back").click();
    await reached(page.getByTestId("lab").locator("details pre"));
    await looksRight(page, "what scrolls in a tool's call, a value, and a session");
  });

  test("output that is longer than its box is, and is scrolled by the arrow keys once it has the focus", async ({ page }) => {
    await askWhereCodeRuns(page, "code:big print a lot");
    await answered(page, /./, 30_000);
    const output = page.getByTestId("code-output");

    await expect(output).toHaveAttribute("tabindex", "0");
    expect((await scrolling(output)).scrolls).toBe(true);
    // Reached the way the keyboard does, which is what a ring that is shown only for the keyboard is shown for
    await output.focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab");
    await expect(output).toBeFocused();
    expect(await output.evaluate((element) => getComputedStyle(element).boxShadow)).not.toBe("none");
    expect(await output.evaluate((element) => element.scrollTop)).toBe(0);
    await page.keyboard.press("PageDown");
    await expect.poll(() => output.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  });

  test("output that fits is not a stop in the order of the page", async ({ page }) => {
    await askWhereCodeRuns(page, "code:hello say hello");
    await answered(page, /./, 20_000);
    const output = page.getByTestId("code-output");

    await expect(output).toContainText("hello from the session");
    expect(await scrolling(output)).toEqual({ scrolls: false, focusable: false });
    await expect(output).not.toHaveAttribute("tabindex", /.*/);
  });

  test("a table and lines of code that run past their box are stops once the reply is written, in boxes that can hold them", async ({
    page,
  }) => {
    await ask(page, "wide: show me what does not fit");
    await answered(page, /./, 20_000);
    const reply = page.getByTestId("lead-message").last();
    const table = reply.locator("table");
    // The box of a table is not a pre, which is for text that has been set and cannot hold a table
    const box = table.locator("xpath=..");

    expect(await box.evaluate((element) => element.tagName)).toBe("DIV");
    await expect.poll(() => scrolling(box)).toEqual({ scrolls: true, focusable: true });
    // The line was written a word at a time and is no taller for it, so the box that holds it is the same size from the
    // first word to the last, and is looked at again as what is in it changes
    const line = reply.locator("pre").first();
    await expect.poll(() => scrolling(line)).toEqual({ scrolls: true, focusable: true });
  });

  test("a box that has more room, or less, once the sidebar is hidden or shown, is a stop only while what is in it does not fit", async ({
    page,
  }) => {
    // Wide enough for the page to have the sidebar beside it, and narrow enough for it to take room from what is read
    await page.setViewportSize({ width: 900, height: 800 });
    await ask(page, "wide: show me what does not fit");
    await answered(page, /./, 20_000);
    const line = page.getByTestId("lead-message").last().locator("pre").nth(1);

    await expect.poll(() => scrolling(line)).toEqual({ scrolls: true, focusable: true });
    await page.getByRole("button", { name: "Hide the sidebar" }).click();
    await expect.poll(() => scrolling(line)).toEqual({ scrolls: false, focusable: false });
    await page.getByRole("button", { name: "Show the sidebar" }).click();
    await expect.poll(() => scrolling(line)).toEqual({ scrolls: true, focusable: true });
  });

  test("a box looks again at what is added to it, changed in it, or taken from it, though it stays the size it was", async ({
    page,
  }) => {
    await askWhereCodeRuns(page, "code:hello say hello");
    await answered(page, /./, 20_000);
    const output = page.getByTestId("code-output");
    await expect(output).toContainText("hello from the session");
    await expect.poll(() => scrolling(output)).toEqual({ scrolls: false, focusable: false });

    // Each is done to the box itself, since the page would draw it again, which is not what is looked at here. The
    // box is as tall and as wide as it was before, and after, and what is in it is not. A bar that came with the extra
    // width would take some of the box's height, and so would a line that is taller for what is on it, and a box that
    // is a different size is seen by the one that watches size, so there is no bar and what is added is out of the line.
    await output.evaluate((element) => {
      element.style.scrollbarWidth = "none";
      element.style.position = "relative";
    });
    const size = () => output.evaluate((element) => [element.clientWidth, element.clientHeight]);
    const before = await size();
    const added = (element: Element, width: string) => {
      const wide = document.createElement("span");
      wide.id = "added";
      wide.style.position = "absolute";
      wide.style.top = "0";
      wide.style.left = "0";
      wide.style.height = "1px";
      wide.style.width = width;
      element.append(wide);
    };
    await output.evaluate(added, "5000px");
    await expect.poll(() => scrolling(output)).toEqual({ scrolls: true, focusable: true });
    expect(await size()).toEqual(before);
    await output.evaluate((element) => element.querySelector("#added")?.remove());
    await expect.poll(() => scrolling(output)).toEqual({ scrolls: false, focusable: false });
    await output.evaluate(added, "10px");
    await expect.poll(() => scrolling(output)).toEqual({ scrolls: false, focusable: false });
    await output.evaluate((element) => ((element.querySelector("#added") as HTMLElement).style.width = "5000px"));
    await expect.poll(() => scrolling(output)).toEqual({ scrolls: true, focusable: true });
    expect(await size()).toEqual(before);
    await output.evaluate((element) => element.querySelector("#added")?.remove());
    await expect.poll(() => scrolling(output)).toEqual({ scrolls: false, focusable: false });
    await output.evaluate((element) => element.append(document.createTextNode("\nmore".repeat(300))));
    await expect.poll(() => scrolling(output)).toEqual({ scrolls: true, focusable: true });
    await output.evaluate((element) => ((element.lastChild as Text).data = "\nless"));
    await expect.poll(() => scrolling(output)).toEqual({ scrolls: false, focusable: false });
  });

  test("a block of code is a stop where it is wider than the page, and only there, as the window changes", async ({ page }) => {
    await askWhereCodeRuns(page, "code:plot draw something");
    await answered(page, /./, 20_000);
    // The first block is the code that was run, which has a line longer than a phone's width
    const code = page.getByTestId("code-cell").first().locator("pre").first();

    for (const size of [SIZES[1], SIZES[0], SIZES[1]]) {
      await page.setViewportSize({ width: size.width, height: size.height });
      await expect.poll(async () => {
        const now = await scrolling(code);

        return now.scrolls === now.focusable;
      }).toBe(true);
    }
    await page.setViewportSize({ width: SIZES[1].width, height: SIZES[1].height });
    await expect.poll(() => scrolling(code)).toEqual({ scrolls: true, focusable: true });
  });
});
