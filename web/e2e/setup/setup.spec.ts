import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { Locator, Page } from "@playwright/test";
import { expect, test } from "../fixtures";
import { arrange, codeInDocker, jobs, lakeFiles, leaveMissing, openSetup, resetSetup, tagOf } from "./state";

// What they arrange is what every test here shares, and each puts it back, so none is run beside another
test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  await resetSetup(page);
  await codeInDocker(page);
  await page.reload();
});

const sidebarButton = (page: Page) =>
  page.getByRole("complementary", { name: "Sidebar" }).getByRole("button", { name: /^Set up/ });

test.describe("the setup", () => {
  test("opens from the sidebar, and closes with the button, with Escape, and with the cross, giving the focus back", async ({ page }) => {
    const dialog = await openSetup(page);

    await expect(dialog.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    await dialog.getByRole("button", { name: "Close", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(sidebarButton(page)).toBeFocused();

    await openSetup(page);
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(sidebarButton(page)).toBeFocused();

    await openSetup(page);
    await dialog.getByRole("button", { name: "Close the setup" }).click();
    await expect(dialog).toHaveCount(0);
  });

  test("says what is done and what is left, step by step, and when everything is ready", async ({ page }) => {
    const dialog = await openSetup(page);
    const steps = dialog.getByRole("list", { name: "What there is to set up" });
    const step = (title: string) => steps.getByRole("listitem", { name: title, exact: true });

    await expect(dialog.getByRole("status")).toHaveText("2 things are left before code can run in Docker.");
    await expect(step("Docker")).toContainText("Done:");
    await expect(step("Docker")).toContainText("Docker 27.3.1 is running");
    await expect(step("Biomni's base environment")).toContainText("To do:");
    await expect(step("Biomni's base environment")).toContainText("Takes a few minutes to build");
    await expect(step("Biomni's data lake")).toContainText("0 of 76 files");
    await expect(step("Biomni's data lake")).toContainText("Optional");
    await expect(step("Biomni's data lake")).toContainText("To do:");
    await expect(step("Model key")).toContainText("OPENAI_API_KEY is not set");
    await expect(step("Model key").getByRole("button", { name: "Add the key" })).toBeVisible();
    await expect(step("Model key")).not.toContainText("Optional");
    await expect(step("Docker")).not.toContainText("Optional");

    // A key given, as it can be in the settings, and the environment built, as it can be outside the page
    expect((await page.request.put("/api/keys/OPENAI_API_KEY", { data: { value: "sk-test" } })).ok()).toBe(true);
    await arrange(page, { docker: { images: [await tagOf(page, "base")] } });
    await page.reload();
    await openSetup(page);

    await expect(dialog.getByRole("status")).toHaveText("Everything code needs is ready.");
    await expect(step("Biomni's base environment")).toContainText("Done:");
    await expect(step("Model key")).toContainText("Done:");
    await expect(step("Model key")).toContainText("The key gpt-5.2 needs is set");
    await expect(step("Model key").getByRole("button", { name: "Add the key" })).toHaveCount(0);
  });

  test("says one thing is left, in the singular", async ({ page }) => {
    expect((await page.request.put("/api/keys/OPENAI_API_KEY", { data: { value: "sk-test" } })).ok()).toBe(true);
    const dialog = await openSetup(page);

    await expect(dialog.getByRole("status")).toHaveText("One thing is left before code can run in Docker.");
  });

  test("does not ask for Docker or an environment when code does not run in Docker", async ({ page }) => {
    expect((await page.request.patch("/api/settings", { data: { code: "local", sandbox: "python" } })).ok()).toBe(true);
    await page.reload();
    const dialog = await openSetup(page);
    const steps = dialog.getByRole("list", { name: "What there is to set up" });

    await expect(steps.getByRole("listitem", { name: "Docker", exact: true })).toContainText("Optional");
    await expect(steps.getByRole("listitem", { name: /environment/ })).toHaveCount(0);
    await expect(dialog.getByRole("status")).toHaveText("One thing is left before code can run in Docker.");
  });

  test("shows the reason when Docker is not running, offers no building, and goes on when it is checked again", async ({ page }) => {
    await arrange(page, { docker: { daemon: "down" } });
    const dialog = await openSetup(page);
    const steps = dialog.getByRole("list", { name: "What there is to set up" });
    const docker = steps.getByRole("listitem", { name: "Docker", exact: true });

    await expect(docker).toContainText("Docker is installed but is not running. It said: Cannot connect to the Docker daemon");
    await expect(docker).toContainText("To do:");
    await expect(steps.getByRole("listitem", { name: "Biomni's base environment" })).toContainText("Waiting:");
    await expect(steps.getByRole("listitem", { name: "Biomni's base environment" })).toContainText("Needs Docker");
    await expect(dialog.getByRole("button", { name: /^Build / })).toHaveCount(0);
    await expect(dialog.getByRole("list", { name: "Stages of the image" }).getByText("Needs Docker")).toHaveCount(3);

    await arrange(page, { docker: { daemon: "up" } });
    await docker.getByRole("button", { name: "Check again" }).click();

    await expect(docker).toContainText("Docker 27.3.1 is running");
    await expect(docker.getByRole("button", { name: "Check again" })).toHaveCount(0);
    await expect(dialog.getByRole("button", { name: "Build Biomni base" })).toBeEnabled();
  });

  test("says Docker is checked while it is, and does not let it be asked again then", async ({ page }) => {
    await arrange(page, { docker: { daemon: "down" } });
    const dialog = await openSetup(page);
    const check = dialog.getByRole("button", { name: "Check again" });
    let answer: () => void = () => {};
    const held = new Promise<void>((resolve) => (answer = resolve));
    await page.route("**/api/setup", async (route) => {
      await held;
      await route.continue();
    });

    await check.click();
    await expect(dialog.getByRole("button", { name: "Checking…" })).toBeDisabled();
    answer();
    await expect(dialog.getByRole("button", { name: "Check again" })).toBeEnabled();
  });

  test("offers each stage of the image, says which is chosen in the settings, and warns when it would run pretending", async ({ page }) => {
    const dialog = await openSetup(page);
    const stages = dialog.getByRole("list", { name: "Stages of the image" });

    await expect(stages.getByRole("listitem")).toHaveCount(3);
    await expect(stages.getByRole("listitem", { name: "Biomni base" })).toContainText("Chosen in the settings");
    await expect(stages.getByRole("listitem", { name: "Biomni bio" })).not.toContainText("Chosen in the settings");
    await expect(stages.getByRole("listitem", { name: "Biomni full" })).toContainText("Adds R and the command-line tools. Takes hours to build.");
    await expect(stages.getByRole("listitem", { name: "Biomni bio" })).toContainText("Not built");
    // The page is tested on a machine that is, or is not, the one the image is for
    const { images } = await (await page.request.get("/api/setup")).json();
    const note = dialog.getByText(/Docker runs the image by pretending/);
    await expect(note).toHaveCount(images.emulated ? 1 : 0);
  });

  test("builds a stage, follows the build, and shows the stage built when it is over", async ({ page }) => {
    await arrange(page, { build: { wait: true, lines: ["#1 load the definition", "#2 install pandas"] } });
    await expect(sidebarButton(page)).toHaveAccessibleName("Set up");
    const dialog = await openSetup(page);
    const base = dialog.getByRole("listitem", { name: "Biomni base" });
    await expect(dialog.getByRole("button", { name: "Build Biomni bio" })).not.toHaveAttribute("title");

    await base.getByRole("button", { name: "Build Biomni base" }).click();

    await expect(base).toContainText("Building");
    await expect(base.getByRole("button", { name: "Build Biomni base" })).toHaveCount(0);
    await expect(base.getByRole("progressbar", { name: /Progress: Building Biomni's base environment/ })).toBeVisible();
    await expect(base).toContainText("#2 install pandas");
    await expect(dialog.getByRole("listitem", { name: "Biomni's base environment" }).first()).toContainText("In progress:");
    await expect(dialog.getByRole("listitem", { name: "Biomni's base environment" }).first()).toContainText("Being built");
    // Only one is built at a time, and what was asked for is the only one stopped
    await expect(dialog.getByRole("button", { name: "Build Biomni bio" })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Build Biomni bio" })).toHaveAttribute("title", "Another stage is being built");
    await expect(dialog.getByRole("button", { name: "Build Biomni full" })).toBeDisabled();
    await expect(base.getByRole("button", { name: "Stop: Building Biomni's base environment" })).toBeEnabled();
    expect((await arrange(page)).started).toBe(true);

    await arrange(page, { release: true });

    await expect(base).toContainText("Built");
    await expect(base.getByRole("progressbar")).toHaveCount(0);
    await expect(base.getByRole("button", { name: "Build Biomni base" })).toHaveCount(0);
    await expect(dialog.getByRole("listitem", { name: "Biomni's base environment" }).first()).toContainText("Done:");
    const { builds, images } = await arrange(page);
    expect(builds).toHaveLength(1);
    expect(builds[0]).toContain(await tagOf(page, "base"));
    expect(images).toEqual([await tagOf(page, "base")]);
  });

  test("shows what a build prints from the stage, with the colours of a terminal taken out", async ({ page }) => {
    // red, in the colour a terminal is told it in
    await arrange(page, { build: { wait: true, lines: ["#1 load the definition"], raw: ["1b5b33316d726564201b5b306d6f6b"] } });
    const dialog = await openSetup(page);
    const base = dialog.getByRole("listitem", { name: "Biomni base" });

    await base.getByRole("button", { name: "Build Biomni base" }).click();
    await base.getByRole("button", { name: "Show what it prints" }).click();

    await expect(dialog.getByRole("tab", { name: "Jobs" })).toHaveAttribute("aria-selected", "true");
    const log = dialog.getByRole("log", { name: "What this printed: Building Biomni's base environment" });
    await expect(log).toContainText("#1 load the definition");
    await expect(log).toContainText("red ok");
    await expect(log).not.toContainText("[31m");
  });

  test("stops a build when asked, and offers the stage to build again", async ({ page }) => {
    await arrange(page, { build: { wait: true } });
    const dialog = await openSetup(page);
    const base = dialog.getByRole("listitem", { name: "Biomni base" });

    await base.getByRole("button", { name: "Build Biomni base" }).click();
    await base.getByRole("button", { name: "Stop: Building Biomni's base environment" }).click();

    await expect(base.getByRole("button", { name: "Build Biomni base" })).toBeVisible();
    await expect(base).toContainText("Not built");
    await expect(base.getByRole("alert")).toHaveCount(0);
    await dialog.getByRole("tab", { name: "Jobs" }).click();
    // The jobs of the tests before are listed too, and the latest is first
    const job = dialog.getByRole("list", { name: "Jobs" }).getByRole("listitem", { name: "Building Biomni's base environment" }).first();
    await expect(job).toContainText("Stopped");
    await expect(job.getByRole("button", { name: /^Stop/ })).toHaveCount(0);
    await dialog.getByRole("button", { name: "Close", exact: true }).click();
    await expect(sidebarButton(page)).toHaveAccessibleName("Set up");
  });

  test("says why a build failed, and shows what it printed", async ({ page }) => {
    await arrange(page, { build: { exit: 1, lines: ["#1 load the definition", "#2 ERROR: no space left"] } });
    const dialog = await openSetup(page);
    const base = dialog.getByRole("listitem", { name: "Biomni base" });

    await base.getByRole("button", { name: "Build Biomni base" }).click();

    await expect(base.getByRole("alert")).toContainText("The last build failed:");
    await expect(base).toContainText("Not built");
    await expect(base.getByRole("button", { name: "Build Biomni base" })).toBeEnabled();
    await base.getByRole("button", { name: "Show what it printed" }).click();
    await expect(dialog.getByRole("log")).toContainText("#2 ERROR: no space left");
  });

  test("lets a build go on when the setup is closed, and shows it done when it is opened again", async ({ page }) => {
    await arrange(page, { build: { wait: true } });
    // The server keeps only the last jobs, so a job is told from those before it by what it is called, not by how many there are
    const before = new Set((await jobs(page)).map((job) => job.id));
    const dialog = await openSetup(page);

    await dialog.getByRole("button", { name: "Build Biomni base" }).click();
    await expect(dialog.getByRole("listitem", { name: "Biomni base" })).toContainText("Building");
    await dialog.getByRole("button", { name: "Close", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(sidebarButton(page)).toHaveAccessibleName("Set up, something is being built or fetched");
    await expect(sidebarButton(page).locator("span[aria-hidden]")).toHaveCount(1);

    await arrange(page, { release: true });
    await expect(sidebarButton(page)).toHaveAccessibleName("Set up");
    await expect(sidebarButton(page).locator("span[aria-hidden]")).toHaveCount(0);

    await openSetup(page);
    await expect(dialog.getByRole("listitem", { name: "Biomni base" })).toContainText("Built");
    const [latest] = await jobs(page);
    expect(before.has(latest.id)).toBe(false);
    expect(latest).toMatchObject({ kind: "image", subject: "base", state: "succeeded" });
  });

  test("shows a build that was begun before the page was opened", async ({ page }) => {
    await arrange(page, { build: { wait: true } });
    expect((await page.request.post("/api/setup/images/base")).status()).toBe(202);

    await page.reload();

    await expect(sidebarButton(page)).toHaveAccessibleName("Set up, something is being built or fetched");
    const dialog = await openSetup(page);
    await expect(dialog.getByRole("listitem", { name: "Biomni base" })).toContainText("Building");
  });

  test("looks at the jobs again when the page is shown again, which is how a build begun elsewhere is found", async ({ page }) => {
    await expect(sidebarButton(page)).toHaveAccessibleName("Set up");
    await arrange(page, { build: { wait: true } });
    expect((await page.request.post("/api/setup/images/base")).status()).toBe(202);
    let looks = 0;
    page.on("request", (request) => {
      if (request.url().endsWith("/api/setup/jobs")) looks += 1;
    });

    // A page that is hidden is not looked for jobs on, and is when it is shown
    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await page.waitForTimeout(300);
    expect(looks).toBe(0);
    await expect(sidebarButton(page)).toHaveAccessibleName("Set up");
    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
      document.dispatchEvent(new Event("visibilitychange"));
    });

    await expect(sidebarButton(page)).toHaveAccessibleName("Set up, something is being built or fetched");
    expect(looks).toBeGreaterThan(0);
  });

  test("says so when the stage was built outside the page, and shows it built", async ({ page }) => {
    const dialog = await openSetup(page);
    await expect(dialog.getByRole("button", { name: "Build Biomni base" })).toBeVisible();
    await arrange(page, { docker: { images: [await tagOf(page, "base")] } });

    await dialog.getByRole("button", { name: "Build Biomni base" }).click();

    await expect(dialog.getByRole("alert")).toHaveText("Biomni's base environment is already built");
    await expect(dialog.getByRole("listitem", { name: "Biomni base" })).toContainText("Built");
    await expect(dialog.getByRole("button", { name: "Build Biomni base" })).toHaveCount(0);
  });

  test("says why when Docker has stopped since it was looked at, and shows that it has", async ({ page }) => {
    const dialog = await openSetup(page);
    await expect(dialog.getByRole("button", { name: "Build Biomni base" })).toBeVisible();
    await arrange(page, { docker: { daemon: "down" } });

    await dialog.getByRole("button", { name: "Build Biomni base" }).click();

    await expect(dialog.getByRole("alert")).toContainText("Docker is installed but is not running");
    await expect(dialog.getByRole("button", { name: /^Build / })).toHaveCount(0);
    await expect(dialog.getByRole("list", { name: "What there is to set up" }).getByRole("listitem", { name: "Docker", exact: true })).toContainText("To do:");
  });

  test("takes the key to the settings, which open at the keys", async ({ page }) => {
    const dialog = await openSetup(page);

    await dialog.getByRole("button", { name: "Add the key" }).click();

    // Not only hidden from what reads the page, as a dialog under another is
    await expect(page.getByRole("dialog", { name: "Set up", includeHidden: true })).toHaveCount(0);
    const settings = page.getByRole("dialog", { name: "Settings" });
    await expect(settings).toBeVisible();
    await expect(settings.getByRole("tab", { name: "Keys" })).toHaveAttribute("aria-selected", "true");

    // The focus goes back to what opened the setup, since what was pressed in it is gone
    await page.keyboard.press("Escape");
    await expect(settings).toHaveCount(0);
    await expect(sidebarButton(page)).toBeFocused();
  });

  test("takes the data lake step to the data lake", async ({ page }) => {
    const dialog = await openSetup(page);

    await dialog.getByRole("button", { name: "Choose files" }).click();

    await expect(dialog.getByRole("tab", { name: "Data lake" })).toHaveAttribute("aria-selected", "true");
  });

  test("says so when what is set up cannot be looked at, and looks again when asked", async ({ page }) => {
    await page.route("**/api/setup", (route) =>
      route.fulfill({ status: 500, json: { error: { code: "broken", message: "The setup is broken" } } }),
    );
    const dialog = await openSetup(page);

    await expect(dialog.getByRole("alert")).toContainText("What is set up could not be looked at. The setup is broken");
    await page.unroute("**/api/setup");
    await dialog.getByRole("button", { name: "Try again" }).click();

    await expect(dialog.getByRole("list", { name: "What there is to set up" })).toBeVisible();
    await expect(dialog.getByRole("alert")).toHaveCount(0);
  });

  test("shows what is being looked at while Docker is slow to say", async ({ page }) => {
    let answer: () => void = () => {};
    const held = new Promise<void>((resolve) => (answer = resolve));
    await page.route("**/api/setup", async (route) => {
      await held;
      await route.continue();
    });
    const dialog = await openSetup(page);

    await expect(dialog.getByRole("status", { name: "Looking at what is set up" })).toBeVisible();
    answer();
    await expect(dialog.getByRole("list", { name: "What there is to set up" })).toBeVisible();
    await expect(dialog.getByRole("status", { name: "Looking at what is set up" })).toHaveCount(0);
  });
});

test.describe("a conversation that cannot run its code yet", () => {
  test("points to the setup, which builds what is missing, and then the conversation can begin", async ({ page }) => {
    expect((await page.request.put("/api/keys/OPENAI_API_KEY", { data: { value: "sk-test" } })).ok()).toBe(true);
    await page.reload();

    await page.getByRole("textbox", { name: "Message" }).fill("Hello from a lab that needs setting up");
    await page.getByRole("button", { name: "Send" }).click();

    const notice = page.getByRole("alert").filter({ hasText: "is not built" });
    await expect(notice).toContainText("Biomni's base environment is not built");
    await notice.getByRole("button", { name: "Set up" }).click();

    const dialog = page.getByRole("dialog", { name: "Set up" });
    await dialog.getByRole("button", { name: "Build Biomni base" }).click();
    await expect(dialog.getByRole("listitem", { name: "Biomni base" })).toContainText("Built");
    await dialog.getByRole("button", { name: "Close", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(notice.getByRole("button", { name: "Set up" })).toBeFocused();

    await page.getByRole("button", { name: "Send" }).click();
    await page.waitForURL(/\/chat\?id=/);
    await expect(page.getByTestId("user-message")).toHaveText("Hello from a lab that needs setting up");
  });

  test("points to the setup when Docker is not running", async ({ page }) => {
    expect((await page.request.put("/api/keys/OPENAI_API_KEY", { data: { value: "sk-test" } })).ok()).toBe(true);
    await arrange(page, { docker: { daemon: "down" } });
    await page.reload();

    await page.getByRole("textbox", { name: "Message" }).fill("Hello with no Docker");
    await page.getByRole("button", { name: "Send" }).click();

    const notice = page.getByRole("alert").filter({ hasText: "Docker" });
    await expect(notice).toContainText("Docker");
    await notice.getByRole("button", { name: "Set up" }).click();
    const dialog = page.getByRole("dialog", { name: "Set up" });
    await expect(dialog.getByRole("list", { name: "What there is to set up" }).getByRole("listitem", { name: "Docker", exact: true })).toContainText("To do:");
  });
});

test.describe("the data lake", () => {
  const filesOf = (dialog: Locator) => dialog.getByRole("list", { name: "Files of the data lake" });

  test("shows what is there and what is not, and where it is kept", async ({ page }) => {
    const files = await lakeFiles(page);
    const missing = files.slice(-3).map((file) => file.name);
    await leaveMissing(page, missing);
    const dialog = await openSetup(page, "Data lake");

    await expect(dialog.getByText("73 of 76 files")).toBeVisible();
    await expect(dialog.getByText(/are there, 730 KB in all/)).toBeVisible();
    await expect(dialog.getByText(/in the workspace\./)).toBeVisible();
    await expect(dialog.getByRole("status")).toHaveText("76 files");
    await expect(filesOf(dialog).getByRole("listitem")).toHaveCount(76);
    for (const name of missing) await expect(dialog.getByRole("button", { name: `Fetch ${name}`, exact: true })).toBeVisible();
    await expect(filesOf(dialog).getByRole("listitem").first()).toContainText("10 KB");
    await expect(filesOf(dialog).getByRole("listitem").first()).toContainText(files[0].name);
    await expect(filesOf(dialog).getByRole("listitem").first()).toContainText("Commercial use");
    const other = files.find((file) => !file.commercial);
    expect(other).toBeDefined();
    const row = filesOf(dialog).getByRole("listitem").filter({ has: page.getByText(other?.name ?? "", { exact: true }) });
    await expect(row).toHaveCount(1);
    await expect(row).not.toContainText("Commercial use");
  });

  test("names the folder the settings name", async ({ page }) => {
    const folder = fs.mkdtempSync(path.join(os.tmpdir(), "vl-e2e-lake-"));
    expect((await page.request.patch("/api/settings", { data: { data_lake: folder } })).ok()).toBe(true);
    const dialog = await openSetup(page, "Data lake");

    await expect(dialog.getByText(/the folder the settings name\./)).toBeVisible();
    await expect(dialog.locator("code", { hasText: fs.realpathSync(folder) })).toBeVisible();
    fs.rmSync(folder, { recursive: true, force: true });
  });

  test("searches the files by the words in their names and in what they are, and shows only those that are not there", async ({ page }) => {
    const files = await lakeFiles(page);
    // The first is one of the two files about affinity capture, and the third is about binding
    await leaveMissing(page, [files[0].name, files[2].name]);
    const dialog = await openSetup(page, "Data lake");
    const search = dialog.getByRole("searchbox", { name: "Search the files" });
    const shown = filesOf(dialog).getByRole("listitem");

    await search.fill("AFFINITY capture");
    await expect(shown).toHaveCount(2);
    await expect(dialog.getByRole("status")).toHaveText("2 of 76 files");
    await search.fill("affinity zzzz");
    await expect(dialog.getByText("No file has all of those words.")).toBeVisible();
    await expect(filesOf(dialog)).toHaveCount(0);

    await search.fill("");
    await dialog.getByRole("checkbox", { name: "Only files that are not there" }).check();
    await expect(shown).toHaveCount(2);
    await expect(dialog.getByRole("status")).toHaveText("2 of 76 files");
    await search.fill("binding");
    await expect(shown).toHaveCount(1);
    await expect(shown).toContainText(files[2].name);
  });

  test("fetches one file, and shows it there, keeping what was searched for", async ({ page }) => {
    const files = await lakeFiles(page);
    await leaveMissing(page, [files[0].name, files[1].name]);
    const dialog = await openSetup(page, "Data lake");
    await dialog.getByRole("searchbox", { name: "Search the files" }).fill(files[0].name);

    await dialog.getByRole("button", { name: `Fetch ${files[0].name}`, exact: true }).click();

    await expect(dialog.getByText("75 of 76 files")).toBeVisible();
    await expect(dialog.getByRole("button", { name: `Fetch ${files[0].name}`, exact: true })).toHaveCount(0);
    await expect(filesOf(dialog).getByRole("listitem")).toHaveCount(1);
    await expect(filesOf(dialog).getByRole("listitem")).toContainText("10 KB");
    await expect(dialog.getByRole("searchbox", { name: "Search the files" })).toHaveValue(files[0].name);
    expect((await arrange(page)).requests).toEqual([files[0].name]);
  });

  test("asks before fetching the files that are not there, which can be called off", async ({ page }) => {
    const files = await lakeFiles(page);
    const missing = files.slice(-3).map((file) => file.name);
    await leaveMissing(page, missing);
    const dialog = await openSetup(page, "Data lake");
    const group = dialog.getByRole("group", { name: "Fetch the data lake" });

    await dialog.getByRole("button", { name: "Fetch the 3 files that are not there" }).click();
    await expect(group).toContainText("This fetches 3 files, which take up to about 11 GB in all.");
    await expect(dialog.getByRole("button", { name: "Fetch the 3 files that are not there" })).toHaveCount(0);
    await group.getByRole("button", { name: "Cancel" }).click();
    await expect(group).toHaveCount(0);
    await expect(dialog.getByRole("button", { name: "Fetch the 3 files that are not there" })).toBeVisible();
    expect((await arrange(page)).requests).toEqual([]);

    await dialog.getByRole("button", { name: "Fetch the 3 files that are not there" }).click();
    await group.getByRole("button", { name: "Start fetching" }).click();

    await expect(dialog.getByText("Every file is there.")).toBeVisible();
    await expect(dialog.getByText("76 of 76 files")).toBeVisible();
    await expect(group).toHaveCount(0);
    expect((await arrange(page)).requests).toEqual(missing);
    await dialog.getByRole("tab", { name: "Overview" }).click();
    const lake = dialog.getByRole("listitem", { name: "Biomni's data lake" });
    await expect(lake).toContainText("Done:");
    await expect(lake).toContainText("76 of 76 files");
    await expect(lake.getByRole("button", { name: "See the files" })).toBeVisible();
  });

  test("offers to fetch only what may be used commercially when that leaves some out, and fetches only that", async ({ page }) => {
    const files = await lakeFiles(page);
    const commercial = files.filter((file) => file.commercial).slice(0, 2).map((file) => file.name);
    const other = files.find((file) => !file.commercial)?.name ?? "";
    await leaveMissing(page, [...commercial, other]);
    const dialog = await openSetup(page, "Data lake");

    await expect(dialog.getByRole("button", { name: "Fetch the 3 files that are not there" })).toBeVisible();
    await dialog.getByRole("button", { name: "Fetch only the 2 for commercial use" }).click();
    await expect(dialog.getByRole("group", { name: "Fetch the data lake" })).toContainText("This fetches 2 files,");
    await dialog.getByRole("button", { name: "Start fetching" }).click();

    await expect(dialog.getByText("75 of 76 files")).toBeVisible();
    expect((await arrange(page)).requests).toEqual(commercial);
    await expect(dialog.getByRole("button", { name: `Fetch ${other}`, exact: true })).toBeVisible();
  });

  test("offers no choice of commercial use when all that is left is, or when only one file is left", async ({ page }) => {
    const files = await lakeFiles(page);
    const commercial = files.filter((file) => file.commercial).slice(0, 2).map((file) => file.name);
    await leaveMissing(page, commercial);
    let dialog = await openSetup(page, "Data lake");

    await expect(dialog.getByRole("button", { name: "Fetch the 2 files that are not there" })).toBeVisible();
    await expect(dialog.getByRole("button", { name: /for commercial use/ })).toHaveCount(0);

    await leaveMissing(page, commercial.slice(0, 1));
    await page.reload();
    dialog = await openSetup(page, "Data lake");
    await expect(dialog.getByRole("button", { name: "Fetch the 1 file that is not there" })).toBeVisible();
  });

  test("offers no choice of commercial use when none of what is left may be used so", async ({ page }) => {
    const other = (await lakeFiles(page)).find((file) => !file.commercial)?.name ?? "";
    await leaveMissing(page, [other]);
    const dialog = await openSetup(page, "Data lake");

    await expect(dialog.getByRole("button", { name: "Fetch the 1 file that is not there" })).toBeVisible();
    await expect(dialog.getByRole("button", { name: /for commercial use/ })).toHaveCount(0);
  });

  test("says every file is there when they are, and offers nothing to fetch", async ({ page }) => {
    await leaveMissing(page, []);
    const dialog = await openSetup(page, "Data lake");

    await expect(dialog.getByText("76 of 76 files")).toBeVisible();
    await expect(dialog.getByText("Every file is there.")).toBeVisible();
    await expect(dialog.getByRole("button", { name: /^Fetch/ })).toHaveCount(0);
  });

  test("follows a fetch as it goes, file by file, and part by part, and shows what it fetched when it is over", async ({ page }) => {
    const files = await lakeFiles(page);
    const missing = files.slice(-3).map((file) => file.name);
    await leaveMissing(page, missing);
    await arrange(page, { hold: [missing[1]] });
    const dialog = await openSetup(page, "Data lake");

    await dialog.getByRole("button", { name: "Fetch the 3 files that are not there" }).click();
    await dialog.getByRole("button", { name: "Start fetching" }).click();

    await expect(dialog.getByRole("progressbar", { name: "Progress: Fetching Biomni's data lake" })).toBeVisible();
    await expect(dialog.getByText(`Fetching ${missing[1]}`)).toBeVisible();
    await expect(dialog.getByText("1 of 3 files · 10 KB fetched · 0 B of 10 KB of this file")).toBeVisible();
    await expect(dialog.getByRole("progressbar", { name: "Progress: Fetching Biomni's data lake" })).toHaveAttribute("aria-valuenow", "33");
    // What is being fetched cannot be asked for again
    for (const name of missing.slice(1)) await expect(dialog.getByRole("button", { name: `Fetch ${name}`, exact: true })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: /^Fetch the \d+ files? that/ })).toHaveCount(0);
    await expect(dialog.getByRole("group", { name: "Fetch the data lake" })).toHaveCount(0);

    await arrange(page, { let: [missing[1]] });

    await expect(dialog.getByText("Every file is there.")).toBeVisible();
    await dialog.getByRole("tab", { name: "Jobs" }).click();
    const job = dialog.getByRole("listitem", { name: "Fetching Biomni's data lake" }).first();
    await expect(job).toContainText("Done");
    await expect(job).toContainText("Fetched 3 files, and 0 were there already");
    await expect(job).toContainText("3 of 3 files · 30 KB fetched");
    await expect(job.getByRole("progressbar")).toHaveCount(0);
  });

  test("stops a fetch that is going on, and keeps the files it had fetched", async ({ page }) => {
    const files = await lakeFiles(page);
    const missing = files.slice(-3).map((file) => file.name);
    await leaveMissing(page, missing);
    await arrange(page, { hold: [missing[1]] });
    const dialog = await openSetup(page, "Data lake");
    await dialog.getByRole("button", { name: "Fetch the 3 files that are not there" }).click();
    await dialog.getByRole("button", { name: "Start fetching" }).click();
    await expect(dialog.getByText(/1 of 3 files/)).toBeVisible();

    await dialog.getByRole("button", { name: "Stop: Fetching Biomni's data lake" }).click();

    // A fetch that waits for the server stops once it has had its answer, and says it is stopping until then
    await expect(dialog.getByRole("button", { name: "Stopping: Fetching Biomni's data lake" })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Stopping: Fetching Biomni's data lake" })).toHaveText("Stopping…");
    await arrange(page, { let: [missing[1]] });
    await expect(dialog.getByRole("progressbar")).toHaveCount(0);
    await expect(dialog.getByText("74 of 76 files")).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Fetch the 2 files that are not there" })).toBeVisible();
    await dialog.getByRole("tab", { name: "Jobs" }).click();
    await expect(dialog.getByRole("listitem", { name: "Fetching Biomni's data lake" }).first()).toContainText("Stopped");
  });

  test("shows the fetch in the overview, with the means to stop it", async ({ page }) => {
    const files = await lakeFiles(page);
    const missing = files.slice(-2).map((file) => file.name);
    await leaveMissing(page, missing);
    await arrange(page, { hold: [missing[0]] });
    expect((await page.request.post("/api/setup/data-lake", { data: { names: missing } })).status()).toBe(202);
    const dialog = await openSetup(page);
    const lake = dialog.getByRole("listitem", { name: "Biomni's data lake" });

    await expect(lake).toContainText("In progress:");
    await expect(lake.getByRole("progressbar")).toBeVisible();
    await expect(lake).toContainText("0 of 2 files");
    await lake.getByRole("button", { name: "Stop: Fetching Biomni's data lake" }).click();
    await arrange(page, { let: [missing[0]] });
    await expect(lake.getByRole("progressbar")).toHaveCount(0);
    await expect(lake).toContainText("To do:");
  });

  test("says why a file could not be fetched, and keeps the others", async ({ page }) => {
    const files = await lakeFiles(page);
    const missing = files.slice(-3).map((file) => file.name);
    await leaveMissing(page, missing);
    await arrange(page, { withhold: [missing[1]] });
    const dialog = await openSetup(page, "Data lake");

    await dialog.getByRole("button", { name: "Fetch the 3 files that are not there" }).click();
    await dialog.getByRole("button", { name: "Start fetching" }).click();

    await expect(dialog.getByText("75 of 76 files")).toBeVisible();
    await dialog.getByRole("tab", { name: "Jobs" }).click();
    const job = dialog.getByRole("listitem", { name: "Fetching Biomni's data lake" }).first();
    await expect(job).toContainText("Failed");
    await expect(job.getByRole("alert")).toContainText("1 of 3 files could not be fetched");
    await job.getByRole("button", { name: "Show what it printed" }).click();
    await expect(job.getByRole("log")).toContainText(`Could not fetch ${missing[1]}`);
  });

  test("says so when a fetch is asked for while another is going on", async ({ page }) => {
    const files = await lakeFiles(page);
    const missing = files.slice(-3).map((file) => file.name);
    await leaveMissing(page, missing);
    const dialog = await openSetup(page, "Data lake");
    await expect(dialog.getByRole("button", { name: `Fetch ${missing[2]}`, exact: true })).toBeEnabled();
    await arrange(page, { hold: [missing[0]] });
    expect((await page.request.post("/api/setup/data-lake", { data: { names: [missing[0]] } })).status()).toBe(202);

    await dialog.getByRole("button", { name: `Fetch ${missing[2]}`, exact: true }).click();

    await expect(dialog.getByRole("alert")).toHaveText("Fetching Biomni's data lake is already running");
    await expect(dialog.getByRole("progressbar")).toBeVisible();
    await expect(dialog.getByRole("button", { name: `Fetch ${missing[2]}`, exact: true })).toBeDisabled();

    // What was refused is not said any longer once something else is asked, and is done
    await dialog.getByRole("button", { name: "Stop: Fetching Biomni's data lake" }).click();
    await expect(dialog.getByRole("button", { name: "Stopping: Fetching Biomni's data lake" })).toBeVisible();
    await expect(dialog.getByRole("alert")).toHaveCount(0);
  });

  test("warns when what is left to fetch may not fit where it is kept", async ({ page }) => {
    await page.route("**/api/setup/data-lake", async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      body.data_lake.free_bytes = 2 * 1024 ** 3;
      await route.fulfill({ response, json: body });
    });
    const dialog = await openSetup(page, "Data lake");

    await expect(dialog.getByText(/, 2\.0 GB free on that disk\./)).toBeVisible();
    await dialog.getByRole("button", { name: "Fetch the 76 files that are not there" }).click();

    await expect(dialog.getByRole("group", { name: "Fetch the data lake" })).toContainText(
      "The rest of the data lake takes up to about 11 GB, and 2.0 GB is free where it is kept.",
    );
  });

  test("does not say how much room is free when that is not known", async ({ page }) => {
    await page.route("**/api/setup/data-lake", async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      body.data_lake.free_bytes = null;
      await route.fulfill({ response, json: body });
    });
    const dialog = await openSetup(page, "Data lake");

    await expect(dialog.getByText(/0 B in all\./)).toBeVisible();
    await expect(dialog.getByText(/free on that disk/)).toHaveCount(0);
    await dialog.getByRole("button", { name: "Fetch the 76 files that are not there" }).click();
    await expect(dialog.getByRole("group", { name: "Fetch the data lake" })).not.toContainText("is free where it is kept");
  });

  test("says so when the data lake cannot be looked at, and looks again when asked", async ({ page }) => {
    await page.route("**/api/setup/data-lake", (route) =>
      route.fulfill({ status: 500, json: { error: { code: "broken", message: "The data lake is broken" } } }),
    );
    const dialog = await openSetup(page, "Data lake");

    await expect(dialog.getByRole("alert")).toContainText("The data lake could not be looked at. The data lake is broken");
    await page.unroute("**/api/setup/data-lake");
    await dialog.getByRole("button", { name: "Try again" }).click();

    await expect(dialog.getByText("0 of 76 files")).toBeVisible();
    await expect(dialog.getByRole("alert")).toHaveCount(0);
  });

  test("shows what is being looked at while the data lake is", async ({ page }) => {
    let answer: () => void = () => {};
    const held = new Promise<void>((resolve) => (answer = resolve));
    await page.route("**/api/setup/data-lake", async (route) => {
      await held;
      await route.continue();
    });
    const dialog = await openSetup(page, "Data lake");

    await expect(dialog.getByRole("status", { name: "Looking at the data lake" })).toBeVisible();
    answer();
    await expect(dialog.getByText("0 of 76 files")).toBeVisible();
    await expect(dialog.getByRole("status", { name: "Looking at the data lake" })).toHaveCount(0);
  });
});

test.describe("the jobs", () => {
  test("say that there are none when none has been run", async ({ page }) => {
    await page.route("**/api/setup/jobs", (route) => route.fulfill({ json: { jobs: [] } }));
    await page.reload();
    const dialog = await openSetup(page, "Jobs");

    await expect(dialog.getByText(/Nothing has been built or fetched since the server started\./)).toBeVisible();
    await expect(dialog.getByRole("list", { name: "Jobs" })).toHaveCount(0);
  });

  test("show what is being looked at while they are", async ({ page }) => {
    let answer: () => void = () => {};
    const held = new Promise<void>((resolve) => (answer = resolve));
    await page.route("**/api/setup/jobs", async (route) => {
      await held;
      await route.continue();
    });
    await page.reload();
    const dialog = await openSetup(page, "Jobs");

    await expect(dialog.getByRole("status", { name: "Looking at the jobs" })).toBeVisible();
    answer();
    await expect(dialog.getByRole("status", { name: "Looking at the jobs" })).toHaveCount(0);
    await expect(dialog.getByRole("list", { name: "Jobs" })).toBeVisible();
  });

  test("are listed with the latest first, each with how it went and when, and show one log at a time", async ({ page }) => {
    await arrange(page, { build: { exit: 1, lines: ["#1 the first build prints this"] } });
    expect((await page.request.post("/api/setup/images/base")).status()).toBe(202);
    await expect.poll(async () => (await jobs(page))[0]?.state).toBe("failed");
    await arrange(page, { build: { exit: 0, lines: ["#1 the second build prints this"] } });
    expect((await page.request.post("/api/setup/images/bio")).status()).toBe(202);
    await expect.poll(async () => (await jobs(page))[0]?.state).toBe("succeeded");
    const dialog = await openSetup(page, "Jobs");
    const list = dialog.getByRole("list", { name: "Jobs" });
    const latest = list.getByRole("listitem").nth(0);
    const before = list.getByRole("listitem").nth(1);

    await expect(latest).toContainText("Building Biomni's bio environment");
    await expect(latest).toContainText("Done");
    await expect(latest).toContainText("Started just now");
    await expect(before).toContainText("Building Biomni's base environment");
    await expect(before).toContainText("Failed");
    await expect(before.getByRole("alert")).toBeVisible();

    await expect(latest.getByRole("button", { name: "Show what it printed" })).not.toHaveAttribute("aria-controls");
    await latest.getByRole("button", { name: "Show what it printed" }).click();
    await expect(latest.getByRole("button", { name: "Hide what it printed" })).toHaveAttribute("aria-expanded", "true");
    const controls = await latest.getByRole("button", { name: "Hide what it printed" }).getAttribute("aria-controls");
    expect(controls).toMatch(/^setup-log-/);
    await expect(latest.locator(`[id="${controls}"]`)).toContainText("#1 the second build prints this");
    await expect(latest.getByRole("log")).toContainText("#1 the second build prints this");
    await before.getByRole("button", { name: "Show what it printed" }).click();
    await expect(before.getByRole("log")).toContainText("#1 the first build prints this");
    await expect(latest.getByRole("log")).toHaveCount(0);
    await expect(latest.getByRole("button", { name: "Show what it printed" })).toHaveAttribute("aria-expanded", "false");
    await before.getByRole("button", { name: "Hide what it printed" }).click();
    await expect(dialog.getByRole("log")).toHaveCount(0);
  });

  test("keep to the last lines of what a job printed, and say how many were dropped", async ({ page }) => {
    const lines = Array.from({ length: 2100 }, (_, number) => `line ${number}`);
    await arrange(page, { build: { exit: 0, lines } });
    expect((await page.request.post("/api/setup/images/base")).status()).toBe(202);
    await expect.poll(async () => (await jobs(page))[0]?.state).toBe("succeeded");
    const dialog = await openSetup(page, "Jobs");

    await dialog.getByRole("listitem").first().getByRole("button", { name: "Show what it printed" }).click();

    await expect(dialog.getByText(/The first 100 lines are not kept/)).toBeVisible();
    const log = dialog.getByRole("log");
    await expect(log).toContainText("line 2099");
    await expect(log).not.toContainText(/\bline 99\b/);
    await expect(log).toContainText(/\bline 100\b/);
  });

  test("say so while what a job printed is being got, and get it when asked again if it could not be", async ({ page }) => {
    await arrange(page, { build: { exit: 0, lines: ["#1 something printed"] } });
    expect((await page.request.post("/api/setup/images/base")).status()).toBe(202);
    await expect.poll(async () => (await jobs(page))[0]?.state).toBe("succeeded");
    await page.route("**/api/setup/jobs/*?log_from=*", (route) => route.abort());
    const dialog = await openSetup(page, "Jobs");
    const job = dialog.getByRole("listitem").first();

    await job.getByRole("button", { name: "Show what it printed" }).click();
    await expect(job.getByText("Getting what it printed…")).toBeVisible();
    await page.unroute("**/api/setup/jobs/*?log_from=*");
    await job.getByRole("button", { name: "Hide what it printed" }).click();
    await job.getByRole("button", { name: "Show what it printed" }).click();

    await expect(job.getByRole("log")).toContainText("#1 something printed");
  });

  test("say so when a job has printed nothing", async ({ page }) => {
    await arrange(page, { build: { exit: 0, lines: [] } });
    expect((await page.request.post("/api/setup/images/base")).status()).toBe(202);
    await expect.poll(async () => (await jobs(page))[0]?.state).toBe("succeeded");
    const dialog = await openSetup(page, "Jobs");

    await dialog.getByRole("listitem").first().getByRole("button", { name: "Show what it printed" }).click();

    await expect(dialog.getByText("It has not printed anything.")).toBeVisible();
  });

  test("follow a job that is going on, and its log as it grows, and stop it", async ({ page }) => {
    await arrange(page, { build: { wait: true, lines: ["#1 first"] } });
    expect((await page.request.post("/api/setup/images/base")).status()).toBe(202);
    const dialog = await openSetup(page, "Jobs");
    const job = dialog.getByRole("listitem").first();

    await expect(job).toContainText("Running");
    await expect(job.getByRole("progressbar")).toBeVisible();
    await job.getByRole("button", { name: "Show what it printed" }).click();
    await expect(job.getByRole("log")).toContainText("#1 first");

    await job.getByRole("button", { name: "Stop: Building Biomni's base environment" }).click();

    await expect(job).toContainText("Stopped");
    await expect(job.getByRole("progressbar")).toHaveCount(0);
    await expect(job.getByRole("log")).toContainText("#1 first");
  });
});

// Holds the answer to the requests that match until it is let go, which is how a test makes something be asked when it is
// not yet answered. What is held is let go when the test ends, since the page is closed.
function holdAnswers(page: Page, pattern: string, method = "GET") {
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  void page.route(pattern, async (route) => {
    if (route.request().method() !== method) return route.fallback();
    await held;

    return route.continue();
  });

  return release;
}

// Says of the images what a test wants said, whatever machine it is run on
async function sayImages(page: Page, images: { emulated: boolean; platform: string }): Promise<void> {
  await page.route("**/api/setup", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    Object.assign(body.images, images);
    await route.fulfill({ response, json: body });
  });
}

test.describe("the setup, on a machine the image is not made for", () => {
  test("says the image is run by pretending, and by what it pretends", async ({ page }) => {
    await sayImages(page, { emulated: true, platform: "linux/amd64" });
    const dialog = await openSetup(page);

    await expect(
      dialog.getByText(
        "This computer is not an amd64 machine, so Docker runs the image by pretending to be one (linux/amd64). Building and running are several times slower that way.",
      ),
    ).toBeVisible();
  });

  test("says nothing of pretending on a machine the image is made for", async ({ page }) => {
    await sayImages(page, { emulated: false, platform: "linux/amd64" });
    const dialog = await openSetup(page);

    await expect(dialog.getByRole("list", { name: "Stages of the image" })).toBeVisible();
    await expect(dialog.getByText(/pretending/)).toHaveCount(0);
  });
});

test.describe("the setup, while it asks", () => {
  test("shows a stage as being built as soon as it is begun, before it is told so", async ({ page }) => {
    await arrange(page, { build: { wait: true } });
    const dialog = await openSetup(page);
    const base = dialog.getByRole("listitem", { name: "Biomni base" });
    await expect(base).toContainText("Not built");
    const release = holdAnswers(page, "**/api/setup");

    await base.getByRole("button", { name: "Build Biomni base" }).click();

    await expect(base).toContainText("Building");
    await expect(base).not.toContainText("Not built");
    release();
  });

  test("lets nothing be built while a build is being asked for", async ({ page }) => {
    await arrange(page, { build: { wait: true } });
    const dialog = await openSetup(page);
    const base = dialog.getByRole("listitem", { name: "Biomni base" });
    const release = holdAnswers(page, "**/api/setup/images/base", "POST");

    await base.getByRole("button", { name: "Build Biomni base" }).click();

    await expect(base.getByRole("button", { name: "Build Biomni base" })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Build Biomni bio" })).toBeDisabled();
    release();
    await expect(base).toContainText("Building");
  });

  test("lets a build be asked to stop only once", async ({ page }) => {
    await arrange(page, { build: { wait: true } });
    expect((await page.request.post("/api/setup/images/base")).status()).toBe(202);
    const dialog = await openSetup(page);
    const base = dialog.getByRole("listitem", { name: "Biomni base" });
    const stop = base.getByRole("button", { name: "Stop: Building Biomni's base environment" });
    const release = holdAnswers(page, "**/api/setup/jobs/*/stop", "POST");

    await stop.click();

    await expect(stop).toBeDisabled();
    release();
    await expect(base.getByRole("button", { name: "Build Biomni base" })).toBeVisible();
  });

  test("lets nothing else be fetched while a fetch is being asked for, and takes the question away once it goes on", async ({ page }) => {
    const missing = (await lakeFiles(page)).slice(-3).map((file) => file.name);
    await leaveMissing(page, missing);
    await arrange(page, { hold: [missing[0]] });
    const dialog = await openSetup(page, "Data lake");
    const group = dialog.getByRole("group", { name: "Fetch the data lake" });
    await dialog.getByRole("button", { name: "Fetch the 3 files that are not there" }).click();
    await expect(group).toBeVisible();
    const release = holdAnswers(page, "**/api/setup/data-lake", "POST");

    await dialog.getByRole("button", { name: `Fetch ${missing[0]}`, exact: true }).click();

    await expect(group.getByRole("button", { name: "Start fetching" })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: `Fetch ${missing[1]}`, exact: true })).toBeDisabled();
    release();
    await expect(dialog.getByRole("progressbar")).toBeVisible();
    await expect(group).toHaveCount(0);
  });

  test("does not say the last build failed once the stage has been built another way", async ({ page }) => {
    await arrange(page, { build: { exit: 1, lines: ["#1 load the definition"] } });
    let dialog = await openSetup(page);
    await dialog.getByRole("button", { name: "Build Biomni base" }).click();
    await expect(dialog.getByRole("alert")).toContainText("The last build failed:");
    await arrange(page, { docker: { images: [await tagOf(page, "base")] } });

    await page.reload();
    dialog = await openSetup(page);

    await expect(dialog.getByRole("listitem", { name: "Biomni base" })).toContainText("Built");
    await expect(dialog.getByRole("listitem", { name: "Biomni base" }).getByRole("alert")).toHaveCount(0);
  });

  test("keeps what it showed when it cannot look again", async ({ page }) => {
    await arrange(page, { docker: { daemon: "down" } });
    const dialog = await openSetup(page);
    const check = dialog.getByRole("button", { name: "Check again" });
    await expect(check).toBeVisible();
    await page.route("**/api/setup", (route) =>
      route.fulfill({ status: 500, json: { error: { code: "broken", message: "The setup is broken" } } }),
    );

    await check.click();

    await expect(check).toBeEnabled();
    await expect(dialog.getByRole("list", { name: "What there is to set up" })).toContainText("Docker is installed but is not running");
    await expect(dialog.getByText("What is set up could not be looked at.")).toHaveCount(0);
  });

  test("looks at the server again when a request is lost on the way to it", async ({ page }) => {
    const dialog = await openSetup(page);
    await expect(dialog.getByRole("button", { name: "Build Biomni base" })).toBeVisible();
    let looks = 0;
    page.on("request", (request) => {
      if (request.url().endsWith("/api/health")) looks += 1;
    });
    await page.route("**/api/setup/images/base", (route) => route.abort());

    await dialog.getByRole("button", { name: "Build Biomni base" }).click();

    // A build that failed in an earlier test is told of in the dialog too, so the alert is the one about the lost request
    await expect(dialog.getByRole("alert").filter({ hasText: "The server cannot be reached" })).toBeVisible();
    await expect.poll(() => looks).toBeGreaterThan(0);
  });
});

test.describe("the jobs, as they are looked at", () => {
  const show = (page: Page, visible: boolean) =>
    page.evaluate((now) => {
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => (now ? "visible" : "hidden") });
      document.dispatchEvent(new Event("visibilitychange"));
    }, visible);

  // Holds the answer to the next look at the jobs, which says what the jobs are when it is asked, and is given when it is
  // let go, by when it is not what they are. Once what it says is taken, what is done after is after it was asked.
  function holdNextLook(page: Page) {
    let release: () => void = () => {};
    let taken: () => void = () => {};
    const held = new Promise<void>((resolve) => (release = resolve));
    const saidSo = new Promise<void>((resolve) => (taken = resolve));
    let next = true;
    void page.route("**/api/setup/jobs", async (route) => {
      if (!next || route.request().method() !== "GET") return route.fallback();
      next = false;
      const response = await route.fetch();
      taken();
      await held;

      return route.fulfill({ response });
    });

    return { release, saidSo };
  }

  test("are not looked at while none is at work", async ({ page }) => {
    await expect(sidebarButton(page)).toHaveAccessibleName("Set up");
    await page.waitForTimeout(300);
    let looks = 0;
    page.on("request", (request) => {
      if (request.url().endsWith("/api/setup/jobs")) looks += 1;
    });

    await page.waitForTimeout(2500);

    expect(looks).toBe(0);
  });

  test("are not taken back to what they were by an answer that comes after a newer one", async ({ page }) => {
    await arrange(page, { build: { wait: true } });
    await expect(sidebarButton(page)).toHaveAccessibleName("Set up");
    const { release, saidSo } = holdNextLook(page);
    await show(page, true);
    await saidSo;
    expect((await page.request.post("/api/setup/images/base")).status()).toBe(202);

    await show(page, true);
    await expect(sidebarButton(page)).toHaveAccessibleName("Set up, something is being built or fetched");
    release();
    await page.waitForTimeout(400);

    await expect(sidebarButton(page)).toHaveAccessibleName("Set up, something is being built or fetched");
  });

  test("are not taken back to what they were by an answer that comes after a job was shown", async ({ page }) => {
    await arrange(page, { build: { wait: true } });
    const dialog = await openSetup(page);
    const base = dialog.getByRole("listitem", { name: "Biomni base" });
    await expect(base.getByRole("button", { name: "Build Biomni base" })).toBeVisible();
    const { release, saidSo } = holdNextLook(page);
    await show(page, true);
    await saidSo;

    await base.getByRole("button", { name: "Build Biomni base" }).click();
    await expect(base.getByRole("button", { name: "Stop: Building Biomni's base environment" })).toBeVisible();
    release();
    await page.waitForTimeout(400);

    await expect(base.getByRole("button", { name: "Stop: Building Biomni's base environment" })).toBeVisible();
  });

  test("have what they printed asked for once, and again only as they print more", async ({ page }) => {
    await arrange(page, { build: { exit: 0, lines: ["#1 one", "#2 two", "#3 three"] } });
    expect((await page.request.post("/api/setup/images/base")).status()).toBe(202);
    await expect.poll(async () => (await jobs(page))[0]?.state).toBe("succeeded");
    const dialog = await openSetup(page, "Jobs");
    const asked: string[] = [];
    page.on("request", (request) => {
      if (request.url().includes("log_from=")) asked.push(request.url());
    });

    await dialog.getByRole("listitem").first().getByRole("button", { name: "Show what it printed" }).click();
    await expect(dialog.getByRole("log")).toContainText("#3 three");
    await page.waitForTimeout(1500);

    expect(asked).toHaveLength(1);
    expect(asked[0]).toMatch(/log_from=0$/);
  });

  test("have what they print added to what is shown, as it is printed", async ({ page }) => {
    const missing = (await lakeFiles(page)).slice(-3).map((file) => file.name);
    await leaveMissing(page, missing);
    await arrange(page, { hold: [missing[1]] });
    expect((await page.request.post("/api/setup/data-lake", { data: { names: missing } })).status()).toBe(202);
    const dialog = await openSetup(page, "Jobs");
    await dialog.getByRole("listitem").first().getByRole("button", { name: "Show what it printed" }).click();
    const log = dialog.getByRole("log");
    await expect(log).toContainText(`Fetched ${missing[0]}`);
    await expect(log).not.toContainText(`Fetched ${missing[2]}`);

    await arrange(page, { let: [missing[1]] });

    await expect(log).toContainText(`Fetched ${missing[2]}`);
    await expect(log).toContainText(`Fetched ${missing[0]}`);
    await expect(dialog.getByText(/lines are not kept/)).toHaveCount(0);
  });

  test("have what they printed asked for only while it is shown, and found when it is shown again", async ({ page }) => {
    const missing = (await lakeFiles(page)).slice(-3).map((file) => file.name);
    await leaveMissing(page, missing);
    await arrange(page, { hold: [missing[1]] });
    expect((await page.request.post("/api/setup/data-lake", { data: { names: missing } })).status()).toBe(202);
    const dialog = await openSetup(page, "Jobs");
    await dialog.getByRole("listitem").first().getByRole("button", { name: "Show what it printed" }).click();
    await expect(dialog.getByRole("log")).toContainText(`Fetched ${missing[0]}`);
    await dialog.getByRole("tab", { name: "Overview" }).click();
    let asked = 0;
    page.on("request", (request) => {
      if (request.url().includes("log_from=")) asked += 1;
    });

    await arrange(page, { let: [missing[1]] });
    await expect.poll(async () => (await jobs(page))[0]?.state).toBe("succeeded");
    await page.waitForTimeout(1500);

    expect(asked).toBe(0);
    await dialog.getByRole("tab", { name: "Jobs" }).click();
    await expect(dialog.getByRole("log")).toContainText(`Fetched ${missing[2]}`);
  });
});
