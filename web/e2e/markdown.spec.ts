import { answered, ask, askWhereCodeRuns, expect, test } from "./fixtures";

// What the scripted lead writes for a message with "markdown:" in it, with what a page must not trust in it

test.describe("what the lead writes", () => {
  test("is shown as the page it is written as", async ({ page }) => {
    await ask(page, "markdown: write it up");
    await answered(page, "Findings");

    const reply = page.getByTestId("lead-message");
    await expect(reply.getByRole("heading", { name: "Findings" })).toBeVisible();
    await expect(reply.locator("strong")).toHaveText("bold");
    await expect(reply.locator("em")).toHaveText("italic");
    await expect(reply.locator("p code")).toHaveText("inline code");
    await expect(reply.getByRole("listitem")).toHaveText(["first point", "second point"]);
    await expect(reply.getByRole("table")).toBeVisible();
    await expect(reply.getByRole("columnheader")).toHaveText(["Gene", "Score"]);
    await expect(reply.getByRole("cell")).toHaveText(["TP53", "0.91"]);
    await expect(reply.locator("pre").first()).toContainText('print("hello")');
  });

  test("has code in a language that is not known, or in none, shown as it is", async ({ page }) => {
    await ask(page, "markdown: write it up");
    await answered(page, "Findings");

    const blocks = page.getByTestId("lead-message").locator("pre");
    await expect(blocks).toHaveCount(3);
    await expect(blocks.nth(1)).toHaveText("plain text here");
    await expect(blocks.nth(2)).toHaveText("no language here");
    await expect(blocks.nth(1).locator('[class*="hljs"]')).toHaveCount(0);
    await expect(blocks.nth(0).locator('[class*="hljs"]').first()).toBeVisible();
    const labels = page.getByTestId("lead-message").locator("pre").locator("xpath=preceding-sibling::div[1]");
    await expect(labels).toHaveText([/Python/, /nonsense/, /Code/]);
  });

  test("has a link that opens elsewhere without handing the page over", async ({ page }) => {
    await ask(page, "markdown: write it up");
    await answered(page, "Findings");

    const link = page.getByTestId("lead-message").getByRole("link", { name: "a paper" });
    await expect(link).toHaveAttribute("href", "https://example.com/paper");
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", /noopener/);
    await expect(link).toHaveAttribute("rel", /noreferrer/);

    const email = page.getByTestId("lead-message").getByRole("link", { name: "an email" });
    await expect(email).toHaveAttribute("href", "mailto:lab@example.com");
    await expect(email).toHaveAttribute("target", "_blank");
  });

  test("has a link to a place in the page that stays in the page", async ({ page }) => {
    await ask(page, "markdown: write it up");
    await answered(page, "Findings");

    const place = page.getByTestId("lead-message").getByRole("link", { name: "A place here" });
    await expect(place).toHaveAttribute("href", "#findings");
    await expect(place).not.toHaveAttribute("target", /.+/);
  });

  test("shows a figure that is one of the conversation's files, and fetches no picture from anywhere else", async ({
    page,
  }) => {
    const elsewhere: string[] = [];
    await page.route(/^https?:\/\/(?!127\.0\.0\.1)/, (route) => {
      elsewhere.push(route.request().url());
      return route.abort();
    });
    const id = await askWhereCodeRuns(page, "markdown: code:plot");
    await answered(page, "Findings", 30_000);

    const reply = page.getByTestId("lead-message");
    const figure = reply.getByRole("img", { name: "The figure" });
    await expect(figure).toHaveAttribute("src", `/api/chats/${id}/files/plots/figure_1.png`);
    await expect.poll(() => figure.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
    await expect(reply.getByRole("img")).toHaveCount(1);
    await expect(reply).toContainText("[A tracker, from elsewhere, is not shown]");
    expect(elsewhere).toEqual([]);
  });

  test("says so where a figure is not one of the conversation's files", async ({ page }) => {
    await ask(page, "markdown: write it up");
    await answered(page, "Findings");

    const reply = page.getByTestId("lead-message");
    await expect(reply).toContainText("[The figure is not one of the files]");
    await expect(reply.getByRole("img")).toHaveCount(0);
  });

  test("runs nothing that was written into it, and shows markup as the text it is", async ({ page }) => {
    await ask(page, "markdown: write it up");
    await answered(page, "Findings");

    const reply = page.getByTestId("lead-message");
    await expect(reply).toContainText("<script>window.__pwned = true</script>");
    await expect(reply.locator("script")).toHaveCount(0);
    expect(await page.evaluate(() => (window as unknown as { __pwned?: boolean }).__pwned)).toBeUndefined();

    // An address that would run code is not a link
    await expect(reply.getByRole("link", { name: "Not a link" })).toHaveCount(0);
    await expect(reply).toContainText("Not a link");
    await expect(reply.locator('a[href^="javascript:"]')).toHaveCount(0);
  });

  test("has code in it that can be copied", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await ask(page, "markdown: write it up");
    await answered(page, "Findings");

    await page.getByTestId("lead-message").getByRole("button", { name: "Copy code" }).first().click();

    await expect(page.getByTestId("lead-message").getByRole("button", { name: "Copied" })).toBeVisible();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('print("hello")');
  });
});
