import { expect, type Locator, type Page } from "@playwright/test";

export const KEYS = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"];

// What the settings are when the server starts
export const INITIAL = {
  model: "gpt-5.2",
  stream: true,
  max_cost: 2,
  code: "none",
  sandbox: "python",
  network: true,
  python: "",
  data_lake: "",
  forward_keys: [] as string[],
};

// Puts the settings and the keys back as the server began with them. The two files of tests run beside each other on one
// server, so each puts back only what it changes, and neither touches what the other does.
export async function resetSettings(page: Page): Promise<void> {
  for (const name of KEYS) expect((await page.request.delete(`/api/keys/${name}`)).ok()).toBe(true);
  expect((await page.request.patch("/api/settings", { data: INITIAL })).ok()).toBe(true);
}

// Takes away the scientists that were added, which leaves the lab's own
export async function resetScientists(page: Page): Promise<void> {
  const { scientists } = await (await page.request.get("/api/scientists")).json();
  for (const scientist of scientists) {
    if (!scientist.builtin) {
      expect((await page.request.delete(`/api/scientists/${encodeURIComponent(scientist.title)}`)).ok()).toBe(true);
    }
  }
}

// Turns every tool back on, which is how the server begins
export async function resetTools(page: Page): Promise<void> {
  expect((await page.request.put("/api/tools", { data: { disabled: [] } })).ok()).toBe(true);
}

export async function settings(page: Page): Promise<typeof INITIAL & { workspace: string }> {
  return (await page.request.get("/api/settings")).json();
}

// Opens the settings from the sidebar, at one of the parts of them if it is named
export async function openSettings(page: Page, tab?: "Model" | "Keys" | "Code" | "Scientists" | "Tools"): Promise<Locator> {
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog).toBeVisible();
  if (tab) await dialog.getByRole("tab", { name: tab }).click();

  return dialog;
}

// Takes away the data and the software that were given to the lab, which are the workspace's, so that no conversation made
// after is given them
export async function resetOwn(page: Page): Promise<void> {
  const own = await (await page.request.get("/api/own")).json();
  for (const data of own.data) {
    expect((await page.request.delete(`/api/own/data/${encodeURIComponent(data.name)}`)).ok()).toBe(true);
  }
  for (const software of own.software) {
    expect((await page.request.delete(`/api/own/software/${encodeURIComponent(software.name)}`)).ok()).toBe(true);
  }
}
