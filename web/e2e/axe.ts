import { resolve } from "node:path";
import type { Page } from "@playwright/test";

interface Found {
  id: string;
  impact: string | null;
  nodes: { target: unknown[]; failureSummary?: string }[];
}

// What axe, which checks a page against the rules for being usable without a mouse or good eyes, finds wrong with what is
// on the page now, one line for each rule, with where. Rules named in skip are not looked at.
export async function accessibilityProblems(page: Page, skip: string[] = []): Promise<string[]> {
  await page.addScriptTag({ path: resolve("node_modules/axe-core/axe.min.js") });
  const found: Found[] = await page.evaluate(async (off) => {
    // axe puts itself on the window, which the page's own types do not know
    const axe = (window as unknown as { axe: { run: (context: Document, options: object) => Promise<{ violations: Found[] }> } }).axe;
    const rules = Object.fromEntries(off.map((id) => [id, { enabled: false }]));

    return (await axe.run(document, { resultTypes: ["violations"], rules })).violations;
  }, skip);

  return found.map(
    ({ id, impact, nodes }) =>
      `${id} (${impact}): ${nodes
        .slice(0, 3)
        .map((node) => `${JSON.stringify(node.target)} ${(node.failureSummary ?? "").split("\n").slice(0, 2).join(" ").trim()}`)
        .join("; ")}`,
  );
}

// How far what is on the page goes past its right edge, which is the page needing to be scrolled sideways
export async function pastTheEdge(page: Page): Promise<number> {
  return page.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth);
}
