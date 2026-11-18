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

// The events of a server, and of what it and its tools ask of the researcher, for a conversation that tells of them
export const server = { server: "genes", title: "Gene tools" };
export const approval = (state: string, request = "r1"): Told => ({
  kind: "approval",
  data: {
    request,
    state,
    ...server,
    ...(state === "waiting"
      ? { tool: "genes_echo", description: "Says the text back.", arguments: JSON.stringify({ text: "ab" }, null, 2) }
      : {}),
  },
});
// A run of a PaperAgent's tool on data that is outside what its method card says, which waits for the researcher to go on
export const SCOPE_WARNINGS = [
  "Outside what the card says: the data's tissue is “liver”, and the card gives the tissue as “mouse brain” (the paper: “CellMapper was only tested on mouse brain tissue.”).",
  "Outside what the card says: the data's sample size is 90 nuclei, and the card says at least 500 nuclei.",
];
export const scopeApproval = (state: string, request = "r1"): Told => ({
  kind: "approval",
  data: {
    request,
    state,
    server: "paperagent:cellmapper",
    title: "CellMapper",
    ...(state === "waiting"
      ? {
          about: "scope",
          tool: "cellmapper_tally",
          description: SCOPE_WARNINGS.join(" "),
          warnings: SCOPE_WARNINGS,
          arguments: JSON.stringify({ counts: [1, 2], scale: 2 }, null, 2),
        }
      : {}),
  },
});
export const asked = (over: { fields?: object; required?: string[]; url?: string | null; text?: string; request?: string } = {}): Told => ({
  kind: "question",
  text: over.text ?? "What is to be ordered?",
  data: { request: over.request ?? "q1", state: "waiting", ...server, fields: over.fields ?? {}, required: over.required ?? [], url: over.url ?? null },
});
export const ended = (state: string, request = "q1"): Told => ({ kind: "question", data: { request, state, ...server } });
export const connection = (state: string, data: Record<string, unknown> = {}, text = ""): Told => ({
  kind: "connection",
  text,
  data: { ...server, state, ...data },
});

// What a server asks for an order, as a form
export const ORDER_FIELDS = {
  name: { type: "string", title: "Sample name", description: "What to call it." },
  kind: { type: "string", enum: ["protein", "dna"], title: "Kind" },
  copies: { type: "integer", default: 1 },
  fresh: { type: "boolean", title: "Fresh sample" },
  tags: { type: "array", items: { type: "string" } },
  picks: { type: "array", items: { enum: ["a", "b", "c"] }, title: "Pick some" },
};
