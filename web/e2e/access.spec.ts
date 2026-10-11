import { expect, test } from "@playwright/test";
import { HOME_HEADING, TOKEN } from "./fixtures";

test.describe("getting in", () => {
  test("a browser that did not open the server's link is told to", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Open the link the server printed" })).toBeVisible();
    await expect(page.getByRole("heading", { name: HOME_HEADING })).toHaveCount(0);
  });

  test("the link with the token lets the browser in and is not left in its address", async ({ page }) => {
    await page.goto(`/?token=${TOKEN}`);

    await expect(page.getByRole("heading", { name: HOME_HEADING })).toBeVisible();
    expect(new URL(page.url()).search).toBe("");

    await page.reload();
    await expect(page.getByRole("heading", { name: HOME_HEADING })).toBeVisible();
  });

  test("a wrong token does not let the browser in", async ({ page }) => {
    await page.goto("/?token=not-the-token");

    await expect(page.getByRole("heading", { name: "Open the link the server printed" })).toBeVisible();
  });

  test("a browser let in after being turned away carries on from Try again", async ({ page, context }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Open the link the server printed" })).toBeVisible();

    // What opening the link in another tab of the same browser does
    const other = await context.newPage();
    await other.goto(`/?token=${TOKEN}`);
    await page.getByRole("button", { name: "Try again" }).click();

    await expect(page.getByRole("heading", { name: HOME_HEADING })).toBeVisible();
  });
});
