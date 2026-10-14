import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

// Events written in a test, for what the scripted lead does not do: the conversation is real, and the events it is told
// of are the ones given

export interface Told {
  kind: string;
  turn?: number;
  speaker?: string | null;
  text?: string;
  data?: Record<string, unknown>;
}

export async function tell(page: Page, events: Told[]): Promise<void> {
  // Titled at once, for the reason that askWhereCodeRuns is
  const made = await page.request.post("/api/chats", { data: { title: `Replay: ${test.info().title}` } });
  expect(made.status()).toBe(201);
  const id: string = (await made.json()).id;

  const body = events
    .map((event, at) => {
      const whole = { id: at + 1, turn: 1, speaker: null, text: "", data: {}, time: 0, ...event };

      return `event: chat\nid: ${at + 1}\ndata: ${JSON.stringify(whole)}\n\n`;
    })
    .join("");
  await page.route("**/api/chats/*/events*", (route) =>
    route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream", "cache-control": "no-cache" },
      // The stream is not made again for a while, which would only tell of the same events
      body: `retry: 600000\n\n${body}`,
    }),
  );
  await page.goto(`/chat?id=${id}`);
}

export const user = (text: string): Told => ({ kind: "user", speaker: "Human researcher", text, data: { attachments: [] } });
export const lead = "Principal Investigator";
export const calling = (id: string, name: string, args: unknown): Told => ({
  kind: "tool_calls",
  speaker: lead,
  text: "Starting.",
  data: { calls: [{ id, name, arguments: JSON.stringify(args) }] },
});
