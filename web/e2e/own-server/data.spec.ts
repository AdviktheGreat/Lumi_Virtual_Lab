import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type { Page } from "@playwright/test";
import { accessibilityProblems, pastTheEdge } from "../axe";
import { expect, HOME_HEADING, test } from "../fixtures";
import { resetOwn, settings } from "./state";

// What is given to the lab is the workspace's, and every conversation made after is given it, so each test takes it away
// again, and none is run beside another
test.describe.configure({ mode: "serial" });

// Where the files that are pointed to are, which is on this machine, as it is where the server is
let scratch = "";

test.beforeEach(async ({ page }) => {
  await resetOwn(page);
  scratch = fs.mkdtempSync(path.join(os.tmpdir(), "vl-e2e-own-"));
  await page.goto("/data");
  await expect(page.getByRole("heading", { name: "Data", level: 1 })).toBeVisible();
});

test.afterEach(async ({ page }) => {
  fs.rmSync(scratch, { recursive: true, force: true });
  await resetOwn(page);
});

const dataForm = (page: Page) => page.getByRole("form", { name: "Give the lab some data" });
const softwareForm = (page: Page) => page.getByRole("form", { name: "Give the lab some software" });
const dataRow = (page: Page, name: string) =>
  page.getByTestId("own-data").filter({ has: page.getByText(name, { exact: true }) });
const softwareRow = (page: Page, name: string) =>
  page.getByTestId("own-software").filter({ has: page.getByText(name, { exact: true }) });
const said = (page: Page, text: string) => page.getByRole("status").filter({ hasText: text });

async function own(page: Page) {
  return (await page.request.get("/api/own")).json();
}

// Chooses a file to upload and says what it is, without adding it
async function choose(page: Page, name: string, content: string | Buffer, description: string) {
  const form = dataForm(page);
  await form.getByLabel("File", { exact: true }).setInputFiles({
    name,
    mimeType: "application/octet-stream",
    buffer: typeof content === "string" ? Buffer.from(content) : content,
  });
  await form.getByLabel("What it is", { exact: true }).fill(description);
}

async function upload(page: Page, name: string, content: string | Buffer, description: string) {
  await choose(page, name, content, description);
  await dataForm(page).getByRole("button", { name: "Add the data" }).click();
  await expect(dataRow(page, name)).toBeVisible();
}

// Switches the form to pointing, and fills it in
async function pointTo(page: Page, where: string, description: string) {
  const form = dataForm(page);
  await form.getByRole("radio", { name: "Pointing to a file or folder on this machine" }).check();
  await form.getByLabel("Full path", { exact: true }).fill(where);
  await form.getByLabel("What it is", { exact: true }).fill(description);
}

async function point(page: Page, where: string, description: string, name: string) {
  await pointTo(page, where, description);
  await dataForm(page).getByRole("button", { name: "Add the data" }).click();
  await expect(dataRow(page, name)).toBeVisible();
}

// Writes a file in the scratch folder, and says where it is
function write(name: string, content: string | Buffer): string {
  const where = path.join(scratch, name);
  fs.writeFileSync(where, content);

  return where;
}

async function addSoftware(page: Page, name: string, description: string) {
  const form = softwareForm(page);
  await form.getByLabel("Name", { exact: true }).fill(name);
  await form.getByLabel("What it is for", { exact: true }).fill(description);
  await form.getByRole("button", { name: "Add the software" }).click();
  await expect(softwareRow(page, name)).toBeVisible();
}

test.describe("the page", () => {
  test("is reached from the sidebar, which says that it is the page that is open", async ({ page }) => {
    await page.goto("/");
    const sidebar = page.getByRole("complementary", { name: "Sidebar" });
    const link = sidebar.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Data" });
    await expect(link).not.toHaveAttribute("aria-current", "page");

    await link.click();

    await expect(page).toHaveURL(/\/data$/);
    await expect(page.getByRole("heading", { name: "Data", level: 1 })).toBeVisible();
    await expect(page).toHaveTitle("Data · Virtual Lab");
    await expect(link).toHaveAttribute("aria-current", "page");

    await sidebar.getByRole("link", { name: "New chat", exact: true }).first().click();
    await expect(page.getByRole("heading", { name: HOME_HEADING })).toBeVisible();
    await expect(link).not.toHaveAttribute("aria-current", "page");
  });

  test("is opened from its own address, and again as it is reloaded", async ({ page }) => {
    await page.reload();

    await expect(page.getByRole("heading", { name: "Data", level: 1 })).toBeVisible();
    await expect(page.getByRole("link", { name: "Data" })).toHaveAttribute("aria-current", "page");
  });

  test("says that nothing is given yet, and what each part is for", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Your data", level: 2 })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Your software", level: 2 })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Biomni's data lake", level: 2 })).toBeVisible();
    await expect(page.getByText("You have not given the lab any data yet.")).toBeVisible();
    await expect(page.getByText("You have not told the lab of any software yet.")).toBeVisible();
    await expect(page.getByText("not in one that is already going")).toBeVisible();
    await expect(page.getByRole("list", { name: "Your data" })).toHaveCount(0);
    await expect(page.getByRole("list", { name: "Files of the data lake" })).toBeVisible();
    await expect(dataForm(page).getByLabel("File", { exact: true })).toBeVisible();
    await expect(dataForm(page).getByText("Up to 20 KB.")).toBeVisible();
  });

  test("is opened from the drawer on a narrow screen, which it closes", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 800 });
    await page.goto("/");
    await page.getByRole("button", { name: "Show the conversations" }).click();
    const sidebar = page.getByRole("complementary", { name: "Sidebar" });

    await sidebar.getByRole("link", { name: "Data" }).click();

    await expect(page).toHaveURL(/\/data$/);
    await expect(page.getByRole("heading", { name: "Data", level: 1 })).toBeVisible();
    await expect(sidebar).not.toBeInViewport();
    expect(await pastTheEdge(page)).toBeLessThanOrEqual(0);
  });
});

test.describe("data that is uploaded", () => {
  test("is kept with what it is, and listed with what is known of it", async ({ page }) => {
    await upload(page, "counts.csv", "gene,count\nTP53,12\n", "  Raw counts\n per gene ");

    const row = dataRow(page, "counts.csv");
    await expect(row).toContainText("Uploaded · 19 B · changed just now");
    await expect(row).toContainText("Raw counts per gene");
    await expect(said(page, "Added counts.csv.")).toBeVisible();
    // What was written is not left in the form, nor the file chosen
    await expect(dataForm(page).getByLabel("What it is", { exact: true })).toHaveValue("");
    await expect(dataForm(page).getByLabel("File", { exact: true })).toHaveValue("");
    // The form that is left is a new one, which has not been tried
    await expect(dataForm(page).getByRole("alert")).toHaveCount(0);
    await expect(dataForm(page).getByLabel("What it is", { exact: true })).not.toHaveAttribute("aria-invalid", "true");

    expect((await own(page)).data).toEqual([
      expect.objectContaining({ name: "counts.csv", description: "Raw counts per gene", source: "uploaded", path: null, kind: "file", bytes: 19 }),
    ]);
    await page.reload();
    await expect(dataRow(page, "counts.csv")).toContainText("Raw counts per gene");
  });

  test("is not sent while there is something to put right, which is said where it is", async ({ page }) => {
    const sent: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().includes("/api/own")) sent.push(request.url());
    });
    const form = dataForm(page);
    // Nothing is said to be wrong in a form that has not been tried
    await expect(form.getByRole("alert")).toHaveCount(0);
    await expect(form.getByLabel("What it is", { exact: true })).not.toHaveAttribute("aria-invalid", "true");

    await form.getByRole("button", { name: "Add the data" }).click();

    await expect(form.getByText("Choose the file to upload.")).toBeVisible();
    await expect(form.getByText("Say what it is, so that the lead knows when to use it.")).toBeVisible();
    await expect(form.getByLabel("File", { exact: true })).toHaveAttribute("aria-invalid", "true");
    await expect(form.getByLabel("What it is", { exact: true })).toHaveAttribute("aria-invalid", "true");
    await expect(form.getByLabel("What it is", { exact: true })).toHaveAccessibleDescription(/Say what it is/);

    // What is put right is no longer said to be wrong
    await choose(page, "counts.csv", "a,b\n", "");
    await expect(form.getByText("Choose the file to upload.")).toHaveCount(0);
    await expect(form.getByText("Say what it is, so that the lead knows when to use it.")).toBeVisible();
    await form.getByRole("button", { name: "Add the data" }).click();
    await expect(form.getByText("Say what it is, so that the lead knows when to use it.")).toBeVisible();
    expect(sent).toEqual([]);

    await form.getByLabel("What it is", { exact: true }).fill("Two columns");
    await expect(form.getByText("Say what it is, so that the lead knows when to use it.")).toHaveCount(0);
    await expect(form.getByLabel("What it is", { exact: true })).not.toHaveAttribute("aria-invalid", "true");
  });

  test("is refused as soon as it is chosen if it is too big, saying where to point to it instead", async ({ page }) => {
    const sent: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().includes("/api/own")) sent.push(request.url());
    });
    const form = dataForm(page);

    await choose(page, "big.bin", Buffer.alloc(20 * 1024 + 1), "Too much");

    await expect(form.getByText("big.bin is larger than the 20 KB that can be uploaded. Point to it where it is on this machine instead.")).toBeVisible();
    await form.getByRole("button", { name: "Add the data" }).click();
    await expect(form.getByRole("alert")).toHaveCount(1);
    expect(sent).toEqual([]);

    await choose(page, "exact.bin", Buffer.alloc(20 * 1024), "Just enough");
    await expect(form.getByRole("alert")).toHaveCount(0);
    await form.getByRole("button", { name: "Add the data" }).click();
    await expect(dataRow(page, "exact.bin")).toContainText("Uploaded · 20 KB");
  });

  test("cannot have the name of data there already, since code finds data by its name", async ({ page }) => {
    await upload(page, "counts.csv", "a\n", "The first");
    const form = dataForm(page);

    await choose(page, "counts.csv", "b\n", "The second");

    await expect(
      form.getByText("There is data named counts.csv already. Code finds data by its name, so delete that first, or rename the file."),
    ).toBeVisible();
    await form.getByRole("button", { name: "Add the data" }).click();
    await expect(page.getByTestId("own-data")).toHaveCount(1);
    await expect(dataRow(page, "counts.csv")).toContainText("The first");

    await choose(page, "counts2.csv", "b\n", "The second");
    await form.getByRole("button", { name: "Add the data" }).click();
    await expect(page.getByTestId("own-data")).toHaveCount(2);
  });

  test("shows how far it has got, and can be called off, which leaves what was written", async ({ page }) => {
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route("**/api/own/data/files*", async (route) => {
      await held;
      await route.continue().catch(() => undefined);
    });
    const form = dataForm(page);
    await choose(page, "slow.csv", "a,b\n", "A slow one");

    await form.getByRole("button", { name: "Add the data" }).click();

    await expect(page.getByRole("progressbar", { name: "Uploading slow.csv" })).toBeVisible();
    await expect(form.getByRole("button", { name: "Adding…" })).toBeDisabled();
    await expect(form.getByLabel("What it is", { exact: true })).toHaveAttribute("readonly", "");
    await form.getByRole("button", { name: "Cancel the upload" }).click();

    await expect(page.getByRole("progressbar")).toHaveCount(0);
    await expect(form.getByRole("button", { name: "Add the data" })).toBeEnabled();
    await expect(form.getByRole("alert")).toHaveCount(0);
    await expect(form.getByLabel("What it is", { exact: true })).toHaveValue("A slow one");
    await expect(page.getByTestId("own-data")).toHaveCount(0);
    expect((await own(page)).data).toEqual([]);
    release();
  });

  test("says why the server refused it, and keeps what was written", async ({ page }) => {
    await page.route("**/api/own/data/files*", (route) =>
      route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "too_many", message: "No more than 500 pieces of data can be given" } }),
      }),
    );
    const form = dataForm(page);
    await choose(page, "counts.csv", "a\n", "Counts");

    await form.getByRole("button", { name: "Add the data" }).click();

    await expect(form.getByRole("alert")).toHaveText("No more than 500 pieces of data can be given");
    await expect(form.getByLabel("What it is", { exact: true })).toHaveValue("Counts");
    await expect(form.getByRole("button", { name: "Add the data" })).toBeEnabled();
    await expect(page.getByTestId("own-data")).toHaveCount(0);
  });
});

test.describe("data that is pointed to", () => {
  test("is left where it is, and listed with where that is", async ({ page }) => {
    const where = write("expression.tsv", "gene\tvalue\nTP53\t1\n");

    // Spaces that came with the path, as they do when it is pasted, are not part of it
    await point(page, `  ${where}  `, "Expression of each gene", "expression.tsv");

    const row = dataRow(page, "expression.tsv");
    await expect(row).toContainText("On this machine · 18 B · changed just now");
    await expect(row).toContainText("Expression of each gene");
    await expect(row.locator("code", { hasText: where })).toBeVisible();
    await expect(said(page, "Added expression.tsv.")).toBeVisible();
    await expect(dataForm(page).getByLabel("Full path", { exact: true })).toHaveValue("");
    // The way it is given by is kept for the next, but not what was written
    await expect(dataForm(page).getByRole("radio", { name: "Pointing to a file or folder on this machine" })).toBeChecked();
    expect(fs.readFileSync(where, "utf8")).toBe("gene\tvalue\nTP53\t1\n");
    expect((await own(page)).data[0]).toMatchObject({ name: "expression.tsv", source: "path", path: where });
  });

  test("can be a folder", async ({ page }) => {
    const folder = path.join(scratch, "images");
    fs.mkdirSync(folder);

    await point(page, folder, "Microscope images", "images");

    await expect(dataRow(page, "images")).toContainText("On this machine · Folder · changed just now");
  });

  test("is asked for in full, and the form keeps what was written while it is not right", async ({ page }) => {
    const form = dataForm(page);
    await pointTo(page, "   ", "Counts");
    await form.getByRole("button", { name: "Add the data" }).click();
    await expect(form.getByText("Give the full path of the file or folder.")).toBeVisible();
    await expect(form.getByLabel("Full path", { exact: true })).toHaveAccessibleDescription(/Give the full path/);

    await form.getByLabel("Full path", { exact: true }).fill("data/counts.csv");
    await form.getByRole("button", { name: "Add the data" }).click();
    await expect(form.getByRole("alert")).toContainText("Give the full path of the file or folder, which 'data/counts.csv' is not");

    const missing = path.join(scratch, "nothing-here.csv");
    await form.getByLabel("Full path", { exact: true }).fill(missing);
    await form.getByRole("button", { name: "Add the data" }).click();
    await expect(form.getByRole("alert")).toContainText("There is nothing at");
    await expect(form.getByLabel("What it is", { exact: true })).toHaveValue("Counts");
    await expect(page.getByTestId("own-data")).toHaveCount(0);
  });

  test("cannot have the name of data there already, whichever way it was given", async ({ page }) => {
    await upload(page, "counts.csv", "a\n", "The first");
    const where = write("counts.csv", "b\n");

    await pointTo(page, where, "The second");
    await dataForm(page).getByRole("button", { name: "Add the data" }).click();

    await expect(dataForm(page).getByRole("alert")).toContainText("There is data named counts.csv already");
    await expect(page.getByTestId("own-data")).toHaveCount(1);
  });

  test("is said to be gone when it is, as the page is shown again, and cannot be looked into", async ({ page }) => {
    const where = write("gone.csv", "a,b\n");
    await point(page, where, "Soon gone", "gone.csv");
    const row = dataRow(page, "gone.csv");
    await expect(row.getByRole("button", { name: "Show the start of gone.csv" })).toBeEnabled();
    await row.getByRole("button", { name: "Show the start of gone.csv" }).click();
    await expect(row.getByRole("region", { name: "The start of gone.csv" })).toBeVisible();

    fs.rmSync(where);
    // The page is shown again, as it is when the person comes back to its tab
    await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));

    await expect(row).toContainText("On this machine · Not there");
    // What is shown of it is not left, since it is no longer what is there
    await expect(row.getByRole("region")).toHaveCount(0);
    await expect(row).toContainText("It is not there any more, so conversations are not given it.");
    await expect(row.getByRole("button", { name: "Show the start of gone.csv" })).toBeDisabled();
    await expect(row.getByRole("button", { name: "Delete gone.csv" })).toBeEnabled();

    fs.writeFileSync(where, "a,b\n");
    await page.reload();
    await expect(dataRow(page, "gone.csv")).not.toContainText("Not there");
  });
});

test.describe("looking into data", () => {
  test("shows the start of a text file, and hides it again", async ({ page }) => {
    const lines = Array.from({ length: 60 }, (_, index) => `row${index + 1},${index}`);
    await upload(page, "long.csv", lines.join("\n"), "Sixty rows");
    const row = dataRow(page, "long.csv");
    const button = row.getByRole("button", { name: "Show the start of long.csv" });
    await expect(button).toHaveAttribute("aria-expanded", "false");

    await button.click();

    const region = row.getByRole("region", { name: "The start of long.csv" });
    await expect(region).toContainText("row1,0");
    await expect(region).toContainText("row40,39");
    await expect(region).not.toContainText("row41,40");
    await expect(row.getByText("Only the start of it is shown.")).toBeVisible();
    await expect(row.getByRole("button", { name: "Hide the start of long.csv" })).toHaveAttribute("aria-expanded", "true");
    await expect(row.getByRole("button", { name: "Hide the start of long.csv" })).toHaveAttribute("aria-controls", /.+/);

    await row.getByRole("button", { name: "Hide the start of long.csv" }).click();
    await expect(region).toHaveCount(0);
  });

  test("says what it cannot show: a file with nothing in it, and one that is not text", async ({ page }) => {
    await upload(page, "empty.txt", "", "Nothing in it");
    await upload(page, "image.bin", Buffer.from([1, 2, 0, 3, 4]), "Not text");

    await dataRow(page, "empty.txt").getByRole("button", { name: "Show the start of empty.txt" }).click();
    await expect(dataRow(page, "empty.txt").getByText("The file is empty.")).toBeVisible();

    await dataRow(page, "image.bin").getByRole("button", { name: "Show the start of image.bin" }).click();
    await expect(dataRow(page, "image.bin").getByText("This is not a text file, so there is nothing of it to show.")).toBeVisible();
  });

  test("lists what is in a folder, folders first, and says how many more there are", async ({ page }) => {
    const folder = path.join(scratch, "many");
    fs.mkdirSync(path.join(folder, "zeta"), { recursive: true });
    for (let number = 0; number < 51; number += 1) fs.writeFileSync(path.join(folder, `file${String(number).padStart(2, "0")}.txt`), "");
    await point(page, folder, "Many files", "many");
    const row = dataRow(page, "many");

    await row.getByRole("button", { name: "Show the start of many" }).click();

    const entries = row.getByRole("list", { name: "In many" }).getByRole("listitem");
    await expect(entries).toHaveCount(50);
    await expect(entries.first()).toHaveText("zetafolder");
    await expect(entries.nth(1)).toHaveText("file00.txtfile");
    await expect(row.getByText("And 2 more.")).toBeVisible();
  });

  test("says when a folder has nothing in it", async ({ page }) => {
    const folder = path.join(scratch, "bare");
    fs.mkdirSync(folder);
    await point(page, folder, "Nothing yet", "bare");

    await dataRow(page, "bare").getByRole("button", { name: "Show the start of bare" }).click();

    await expect(dataRow(page, "bare").getByText("The folder is empty.")).toBeVisible();
  });

  test("says so when the server cannot show it", async ({ page }) => {
    await upload(page, "counts.csv", "a\n", "Counts");
    await page.route("**/api/own/data/counts.csv/preview", (route) =>
      route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "internal", message: "The disk is not answering" } }),
      }),
    );

    await dataRow(page, "counts.csv").getByRole("button", { name: "Show the start of counts.csv" }).click();

    await expect(dataRow(page, "counts.csv").getByRole("alert")).toHaveText("The disk is not answering");
  });
});

test.describe("what data is said to be", () => {
  test("is changed, in words that are kept tidy, and the name stays as it is", async ({ page }) => {
    await upload(page, "counts.csv", "a\n", "Old words");
    const row = dataRow(page, "counts.csv");

    await row.getByRole("button", { name: "Change what counts.csv is" }).click();

    const form = row.getByRole("form", { name: "What counts.csv is" });
    await expect(form.getByLabel("What it is")).toHaveValue("Old words");
    await expect(form.getByLabel("What it is")).toBeFocused();
    await expect(row.getByRole("button", { name: "Change what counts.csv is" })).toBeDisabled();
    await form.getByLabel("What it is").fill("  New\n words ");
    const sent = page.waitForRequest((request) => request.method() === "PATCH" && request.url().endsWith("/api/own/data/counts.csv"));
    await form.getByRole("button", { name: "Save" }).click();

    expect((await sent).postDataJSON()).toEqual({ description: "New words" });
    await expect(row).toContainText("New words");
    await expect(row.getByRole("form")).toHaveCount(0);
    await expect(said(page, "Saved what counts.csv is.")).toBeVisible();
    expect((await own(page)).data[0]).toMatchObject({ name: "counts.csv", description: "New words" });
  });

  test("must still be said, and is left as it was when it is given up", async ({ page }) => {
    await upload(page, "counts.csv", "a\n", "Old words");
    const row = dataRow(page, "counts.csv");
    await row.getByRole("button", { name: "Change what counts.csv is" }).click();
    const form = row.getByRole("form", { name: "What counts.csv is" });
    const sent: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "PATCH") sent.push(request.url());
    });

    await form.getByLabel("What it is").fill("   ");
    await form.getByRole("button", { name: "Save" }).click();
    await expect(form.getByText("Say what it is, so that the lead knows when to use it.")).toBeVisible();
    await expect(form.getByLabel("What it is")).toHaveAttribute("aria-invalid", "true");
    expect(sent).toEqual([]);

    await form.getByLabel("What it is").fill("Thrown away");
    await form.getByRole("button", { name: "Cancel" }).click();

    await expect(row).toContainText("Old words");
    await expect(row.getByRole("form")).toHaveCount(0);
    expect((await own(page)).data[0].description).toBe("Old words");
  });

  test("is left as it was, with the reason said, when the server refuses", async ({ page }) => {
    await upload(page, "counts.csv", "a\n", "Old words");
    await page.route("**/api/own/data/counts.csv", (route) =>
      route.request().method() === "PATCH"
        ? route.fulfill({
            status: 404,
            contentType: "application/json",
            body: JSON.stringify({ error: { code: "not_found", message: "There is no data of yours with that name" } }),
          })
        : route.continue(),
    );
    const row = dataRow(page, "counts.csv");
    await row.getByRole("button", { name: "Change what counts.csv is" }).click();
    const form = row.getByRole("form", { name: "What counts.csv is" });
    await form.getByLabel("What it is").fill("Other words");

    await form.getByRole("button", { name: "Save" }).click();

    await expect(form.getByRole("alert")).toHaveText("There is no data of yours with that name");
    await expect(form.getByLabel("What it is")).toHaveValue("Other words");
    await expect(form.getByRole("button", { name: "Save" })).toBeEnabled();
  });
});

test.describe("giving data up", () => {
  test("deletes what was uploaded, after asking, and puts the focus where the person can go on", async ({ page }) => {
    const { workspace } = await settings(page);
    await upload(page, "counts.csv", "a\n", "Counts");
    const kept = path.join(workspace, "own_data", "counts.csv");
    expect(fs.existsSync(kept)).toBe(true);
    const button = dataRow(page, "counts.csv").getByRole("button", { name: "Delete counts.csv" });

    await button.click();

    const question = page.getByRole("alertdialog", { name: "Delete counts.csv?" });
    await expect(question).toContainText("This deletes the copy of it that the lab keeps.");
    await question.getByRole("button", { name: "Keep" }).click();
    await expect(question).toHaveCount(0);
    await expect(button).toBeFocused();
    await expect(dataRow(page, "counts.csv")).toBeVisible();
    expect(fs.existsSync(kept)).toBe(true);

    await button.click();
    await question.getByRole("button", { name: "Delete" }).click();

    await expect(dataRow(page, "counts.csv")).toHaveCount(0);
    await expect(said(page, "Deleted counts.csv.")).toBeVisible();
    await expect(page.getByText("You have not given the lab any data yet.")).toBeVisible();
    await expect(dataForm(page).getByRole("button", { name: "Add the data" })).toBeFocused();
    expect((await own(page)).data).toEqual([]);
    expect(fs.existsSync(kept)).toBe(false);
  });

  test("leaves what was pointed to where it is, and says so", async ({ page }) => {
    const where = write("mine.csv", "a\n");
    await point(page, where, "Mine", "mine.csv");

    await dataRow(page, "mine.csv").getByRole("button", { name: "Delete mine.csv" }).click();

    const question = page.getByRole("alertdialog", { name: "Delete mine.csv?" });
    await expect(question).toContainText(`What is at ${where} is left where it is.`);
    await question.getByRole("button", { name: "Delete" }).click();

    await expect(dataRow(page, "mine.csv")).toHaveCount(0);
    expect((await own(page)).data).toEqual([]);
    expect(fs.readFileSync(where, "utf8")).toBe("a\n");
  });

  test("says why when the server refuses, and leaves the data in the list", async ({ page }) => {
    await upload(page, "counts.csv", "a\n", "Counts");
    await page.route("**/api/own/data/counts.csv", (route) =>
      route.request().method() === "DELETE"
        ? route.fulfill({
            status: 500,
            contentType: "application/json",
            body: JSON.stringify({ error: { code: "internal", message: "The file is in use" } }),
          })
        : route.continue(),
    );

    await dataRow(page, "counts.csv").getByRole("button", { name: "Delete counts.csv" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();

    await expect(page.getByRole("alert").filter({ hasText: "The file is in use" })).toBeVisible();
    await expect(dataRow(page, "counts.csv")).toBeVisible();
  });
});

test.describe("software", () => {
  test("is kept with what it is for, and listed", async ({ page }) => {
    await addSoftware(page, "  Sam   tools ", "Reads\n and writes BAM  files");

    const row = softwareRow(page, "Sam tools");
    await expect(row).toContainText("Reads and writes BAM files");
    await expect(said(page, "Saved Sam tools.")).toBeVisible();
    await expect(softwareForm(page).getByLabel("Name", { exact: true })).toHaveValue("");
    await expect(softwareForm(page).getByLabel("What it is for", { exact: true })).toHaveValue("");
    expect((await own(page)).software).toEqual([{ name: "Sam tools", description: "Reads and writes BAM files" }]);

    await page.reload();
    await expect(softwareRow(page, "Sam tools")).toContainText("Reads and writes BAM files");
  });

  test("needs a name and what it is for, and is not sent until it has them", async ({ page }) => {
    const sent: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "PUT" && request.url().includes("/api/own")) sent.push(request.url());
    });
    const form = softwareForm(page);

    await form.getByRole("button", { name: "Add the software" }).click();

    await expect(form.getByText("Name the software.")).toBeVisible();
    await expect(form.getByText("Say what it is, so that the lead knows when to use it.")).toBeVisible();
    await expect(form.getByLabel("Name", { exact: true })).toHaveAttribute("aria-invalid", "true");
    expect(sent).toEqual([]);

    await form.getByLabel("Name", { exact: true }).fill("samtools");
    await expect(form.getByText("Name the software.")).toHaveCount(0);
  });

  test("cannot be new with the name of software there already, which is changed instead", async ({ page }) => {
    await addSoftware(page, "samtools", "BAM files");
    const form = softwareForm(page);

    await form.getByLabel("Name", { exact: true }).fill(" samtools ");
    await form.getByLabel("What it is for", { exact: true }).fill("Other");
    await form.getByRole("button", { name: "Add the software" }).click();

    await expect(form.getByText("There is software named samtools. Change that instead, or choose another name.")).toBeVisible();
    expect((await own(page)).software).toEqual([{ name: "samtools", description: "BAM files" }]);
  });

  test("is changed in place, by what it is for, and not by its name", async ({ page }) => {
    await addSoftware(page, "samtools", "BAM files");
    const row = softwareRow(page, "samtools");
    await expect(said(page, "Saved samtools.")).toBeVisible();

    await row.getByRole("button", { name: "Change samtools" }).click();

    // What was done before is not said beside what is being done now
    await expect(said(page, "Saved samtools.")).toHaveCount(0);
    const form = page.getByRole("form", { name: "Change samtools" });
    await expect(form.getByLabel("Name", { exact: true })).toHaveAttribute("readonly", "");
    await expect(form.getByLabel("What it is for", { exact: true })).toBeFocused();
    await form.getByLabel("What it is for", { exact: true }).fill("BAM and CRAM files, version 1.20");
    await form.getByRole("button", { name: "Save" }).click();

    await expect(softwareRow(page, "samtools")).toContainText("BAM and CRAM files, version 1.20");
    await expect(page.getByRole("form", { name: "Change samtools" })).toHaveCount(0);
    expect((await own(page)).software).toEqual([{ name: "samtools", description: "BAM and CRAM files, version 1.20" }]);
  });

  test("is left as it was when the change is given up", async ({ page }) => {
    await addSoftware(page, "samtools", "BAM files");
    await softwareRow(page, "samtools").getByRole("button", { name: "Change samtools" }).click();
    const form = page.getByRole("form", { name: "Change samtools" });

    await form.getByLabel("What it is for", { exact: true }).fill("Thrown away");
    await form.getByRole("button", { name: "Cancel" }).click();

    await expect(softwareRow(page, "samtools")).toContainText("BAM files");
    expect((await own(page)).software[0].description).toBe("BAM files");
  });

  test("is deleted after asking, which does not uninstall it", async ({ page }) => {
    await addSoftware(page, "samtools", "BAM files");
    await addSoftware(page, "bwa", "Aligner");

    const button = softwareRow(page, "samtools").getByRole("button", { name: "Delete samtools" });
    await button.click();
    const question = page.getByRole("alertdialog", { name: "Delete samtools?" });
    await expect(question).toContainText("It is not uninstalled from anywhere.");
    await question.getByRole("button", { name: "Keep" }).click();
    await expect(softwareRow(page, "samtools")).toBeVisible();
    await expect(button).toBeFocused();

    await button.click();
    await question.getByRole("button", { name: "Delete" }).click();

    await expect(softwareRow(page, "samtools")).toHaveCount(0);
    // The button that asked is gone, so the focus is put where the person can go on
    await expect(softwareForm(page).getByRole("button", { name: "Add the software" })).toBeFocused();
    await expect(softwareRow(page, "bwa")).toBeVisible();
    await expect(said(page, "Deleted samtools.")).toBeVisible();
    expect((await own(page)).software).toEqual([{ name: "bwa", description: "Aligner" }]);
  });

  test("that is being changed keeps its form, with what was written in it, when other software is deleted", async ({ page }) => {
    await addSoftware(page, "samtools", "BAM files");
    await addSoftware(page, "bwa", "Aligner");
    await softwareRow(page, "samtools").getByRole("button", { name: "Change samtools" }).click();
    const form = page.getByRole("form", { name: "Change samtools" });
    await form.getByLabel("What it is for").fill("Half written");

    await page.getByRole("button", { name: "Delete bwa" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();

    await expect(softwareRow(page, "bwa")).toHaveCount(0);
    await expect(form.getByLabel("What it is for")).toHaveValue("Half written");
    await form.getByRole("button", { name: "Save" }).click();
    await expect(softwareRow(page, "samtools")).toContainText("Half written");
    await expect(form).toHaveCount(0);
  });
});

test.describe("looking at what was given", () => {
  test("says when it cannot be looked at, and tries again", async ({ page }) => {
    let refuse = true;
    await page.route("**/api/own", (route) =>
      refuse && route.request().method() === "GET"
        ? route.fulfill({
            status: 500,
            contentType: "application/json",
            body: JSON.stringify({ error: { code: "internal", message: "The workspace is locked" } }),
          })
        : route.continue(),
    );
    await page.reload();

    const failed = page.getByRole("alert").filter({ hasText: "What you gave the lab could not be looked at. The workspace is locked" });
    await expect(failed).toHaveCount(2);
    await expect(dataForm(page)).toHaveCount(0);

    refuse = false;
    await page.getByRole("button", { name: "Try again" }).first().click();

    await expect(dataForm(page)).toBeVisible();
    await expect(softwareForm(page)).toBeVisible();
    await expect(failed).toHaveCount(0);
  });

  test("tries again from the software's part as well, which is the same look", async ({ page }) => {
    let refuse = true;
    await page.route("**/api/own", (route) =>
      refuse && route.request().method() === "GET"
        ? route.fulfill({
            status: 500,
            contentType: "application/json",
            body: JSON.stringify({ error: { code: "internal", message: "The workspace is locked" } }),
          })
        : route.continue(),
    );
    await page.reload();
    await expect(page.getByRole("button", { name: "Try again" })).toHaveCount(2);

    refuse = false;
    await page.getByRole("button", { name: "Try again" }).last().click();

    await expect(softwareForm(page)).toBeVisible();
    await expect(dataForm(page)).toBeVisible();
  });

  test("keeps what is shown when it cannot be looked at again", async ({ page }) => {
    await upload(page, "counts.csv", "a\n", "Counts");
    await page.route("**/api/own", (route) => (route.request().method() === "GET" ? route.abort() : route.continue()));

    // The look has failed once the server is looked at, which is what is done after it
    const checked = page.waitForRequest((request) => request.url().endsWith("/api/health"));
    await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
    await checked;

    await expect(dataRow(page, "counts.csv")).toBeVisible();
    await expect(page.getByText("could not be looked at")).toHaveCount(0);
  });

  test("does not take back what was given for an answer that was asked for before it was given", async ({ page }) => {
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    // The look is answered with what was there when it was made, but only once what is given has been shown
    await page.route("**/api/own", async (route) => {
      if (route.request().method() !== "GET") return route.continue();
      const response = await route.fetch();
      await held;

      return route.fulfill({ response });
    });
    await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
    await upload(page, "counts.csv", "a\n", "Counts");
    const answered = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/own");

    release();
    await answered;
    await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));

    await expect(dataRow(page, "counts.csv")).toBeVisible();
    await expect(page.getByText("You have not given the lab any data yet.")).toHaveCount(0);
  });
});

test.describe("when a request is lost on the way to the server", () => {
  // Loses what asks for a change, as a dropped connection does, which is when the page looks at whether the server is there
  const lost = async (page: Page) => {
    await page.route("**/api/own/**", (route) => (route.request().method() === "GET" ? route.continue() : route.abort()));
  };
  const looked = (page: Page) => page.waitForRequest((request) => request.url().endsWith("/api/health"));

  test("the server is looked at when data is given", async ({ page }) => {
    await lost(page);
    const checked = looked(page);

    await pointTo(page, write("a.csv", "a\n"), "Counts");
    await dataForm(page).getByRole("button", { name: "Add the data" }).click();

    await checked;
    await expect(dataForm(page).getByRole("alert")).toBeVisible();
    await expect(dataForm(page).getByLabel("What it is", { exact: true })).toHaveValue("Counts");
  });

  test("the server is looked at when what data is said to be is changed", async ({ page }) => {
    await upload(page, "counts.csv", "a\n", "Counts");
    await lost(page);
    const row = dataRow(page, "counts.csv");
    await row.getByRole("button", { name: "Change what counts.csv is" }).click();
    const checked = looked(page);

    await row.getByRole("button", { name: "Save" }).click();

    await checked;
    await expect(row.getByRole("alert")).toBeVisible();
  });

  test("the server is looked at when data is given up", async ({ page }) => {
    await upload(page, "counts.csv", "a\n", "Counts");
    await lost(page);
    await dataRow(page, "counts.csv").getByRole("button", { name: "Delete counts.csv" }).click();
    const checked = looked(page);

    await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();

    await checked;
    await expect(dataRow(page, "counts.csv")).toBeVisible();
  });

  test("the server is looked at when a look at data is asked for", async ({ page }) => {
    await upload(page, "counts.csv", "a\n", "Counts");
    await page.route("**/api/own/data/counts.csv/preview", (route) => route.abort());
    const checked = looked(page);

    await dataRow(page, "counts.csv").getByRole("button", { name: "Show the start of counts.csv" }).click();

    await checked;
    await expect(dataRow(page, "counts.csv").getByRole("alert")).toBeVisible();
  });

  test("the server is looked at when software is given", async ({ page }) => {
    await lost(page);
    const form = softwareForm(page);
    await form.getByLabel("Name", { exact: true }).fill("samtools");
    await form.getByLabel("What it is for", { exact: true }).fill("BAM files");
    const checked = looked(page);

    await form.getByRole("button", { name: "Add the software" }).click();

    await checked;
    await expect(form.getByRole("alert")).toBeVisible();
    await expect(form.getByLabel("Name", { exact: true })).toHaveValue("samtools");
  });

  test("the server is looked at when software is given up", async ({ page }) => {
    await addSoftware(page, "samtools", "BAM files");
    await lost(page);
    await softwareRow(page, "samtools").getByRole("button", { name: "Delete samtools" }).click();
    const checked = looked(page);

    await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();

    await checked;
    await expect(softwareRow(page, "samtools")).toBeVisible();
  });
});

test.describe("what a conversation is given", () => {
  test("is what the lab has been given by the time it is made, and not what is given after", async ({ page }) => {
    const before = await (await page.request.post("/api/chats", { data: {} })).json();
    expect(before.config.data).toEqual([]);

    await upload(page, "counts.csv", "a\n", "Counts");
    await point(page, write("mine.csv", "a\n"), "Mine", "mine.csv");
    await addSoftware(page, "samtools", "BAM files");
    const after = await (await page.request.post("/api/chats", { data: {} })).json();

    expect(after.config.data).toEqual(["counts.csv", "mine.csv"]);
    expect(after.config.software).toEqual(["samtools"]);
    const still = await (await page.request.get(`/api/chats/${before.id}`)).json();
    expect(still.config.data).toEqual([]);
    expect(still.config.software).toEqual([]);
  });
});

test.describe("the page as a whole", () => {
  test("has nothing wrong that axe can find, with data, software, a preview, and a form to change one open", async ({ page }) => {
    await upload(page, "counts.csv", "gene,count\nTP53,12\n", "Raw counts per gene");
    await point(page, write("mine.csv", "a\n"), "Mine", "mine.csv");
    await addSoftware(page, "samtools", "BAM files");
    await dataRow(page, "counts.csv").getByRole("button", { name: "Show the start of counts.csv" }).click();
    await expect(dataRow(page, "counts.csv").getByRole("region")).toBeVisible();
    await dataRow(page, "mine.csv").getByRole("button", { name: "Change what mine.csv is" }).click();
    await softwareRow(page, "samtools").getByRole("button", { name: "Change samtools" }).click();
    await dataForm(page).getByRole("button", { name: "Add the data" }).click();
    await expect(dataForm(page).getByRole("alert").first()).toBeVisible();

    expect(await accessibilityProblems(page)).toEqual([]);
  });

  test("has nothing wrong that axe can find with a question open, and in the dark", async ({ page }) => {
    await upload(page, "counts.csv", "a\n", "Counts");
    await page.emulateMedia({ colorScheme: "dark" });
    await page.reload();
    await dataRow(page, "counts.csv").getByRole("button", { name: "Delete counts.csv" }).click();
    await expect(page.getByRole("alertdialog")).toBeVisible();

    expect(await accessibilityProblems(page)).toEqual([]);
  });

  test("does not go past the edge of a narrow screen with names and paths that are long", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 800 });
    const long = `${"a-very-long-name-".repeat(6)}counts.csv`;
    await upload(page, long, "a\n", "A name that does not fit".repeat(10));
    const folder = path.join(scratch, "b".repeat(60));
    fs.mkdirSync(folder);
    await point(page, folder, "Far away", "b".repeat(60));
    await addSoftware(page, "s".repeat(90), "word ".repeat(100).trim());

    expect(await pastTheEdge(page)).toBeLessThanOrEqual(0);
  });
});

test("is headed in the order it is read, with a heading for each part", async ({ page }) => {
  const headings = await page.getByRole("main").getByRole("heading").allTextContents();

  expect(headings).toEqual(["Data", "Your data", "Add data", "Your software", "Add software", "Biomni's data lake"]);
});
