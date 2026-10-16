import { expect, HOME_HEADING, refusals, test } from "./fixtures";

test.describe("what a page is allowed", () => {
  test("every page of the interface has a policy that lets it run its own scripts and nothing from elsewhere", async ({ page }) => {
    for (const path of ["/", "/chat", "/chat?id=2026-01-01_0000_nothing-here", "/settings"]) {
      const response = await page.goto(path);
      const policy = response?.headers()["content-security-policy"] ?? "";

      expect(policy, path).toContain("default-src 'self'");
      expect(policy, path).toMatch(/script-src 'self'( 'sha256-[A-Za-z0-9+/=]+')+;/);
      expect(policy, path).not.toContain("script-src 'self' 'unsafe-inline'");
      expect(policy, path).toContain("frame-ancestors 'none'");
    }
  });

  test("a script that gets into a page does not run, and is told of", async ({ page }) => {
    const seen = refusals.get(page) ?? [];
    await expect(page.getByRole("heading", { name: HOME_HEADING })).toBeVisible();

    await page.evaluate(() => {
      const script = document.createElement("script");
      script.textContent = "window.injected = true";
      document.body.append(script);
    });

    expect(await page.evaluate(() => "injected" in window)).toBe(false);
    await expect.poll(() => seen.length).toBeGreaterThan(0);
    expect(seen[0]).toContain("inline script");
    // It was meant, so it is not what the test is failed for
    seen.length = 0;
  });

  test("what the page loads from another address is not loaded", async ({ page }) => {
    const seen = refusals.get(page) ?? [];
    await page.evaluate(() => {
      const picture = new Image();
      picture.src = "http://example.invalid/x.png";
      document.body.append(picture);
    });

    await expect.poll(() => seen.length).toBeGreaterThan(0);
    expect(seen[0]).toContain("img-src");
    seen.length = 0;
  });
});
