import { spawn, type ChildProcess } from "node:child_process";
import net from "node:net";
import path from "node:path";
import { expect, type Page } from "@playwright/test";

// The Python that has virtual-lab[server] installed, which also runs the test server of the MCP library's own tests
const PYTHON = process.env.VIRTUAL_LAB_PYTHON ?? "python3";
const TEST_SERVER = path.resolve(__dirname, "../../../tests/mcp_test_server.py");

// How a server of one's own that is the test server, started as a program on this computer, is described
export function program(extra: Record<string, unknown> = {}): Record<string, unknown> {
  return { command: [PYTHON, TEST_SERVER], ...extra };
}

// Sets a server up, as the settings do, in full
export async function setUp(page: Page, name: string, entry: Record<string, unknown>): Promise<void> {
  const response = await page.request.put(`/api/mcp/servers/${name}`, { data: { entry } });
  expect(response.status(), await response.text()).toBe(200);
}

// Forgets a server, which is not an error if it was not set up
export async function forget(page: Page, name: string): Promise<void> {
  const response = await page.request.delete(`/api/mcp/servers/${name}`);
  expect([200, 404]).toContain(response.status());
}

export interface Server {
  name: string;
  added: boolean;
  enabled: boolean;
  preset: boolean;
  problem: string | null;
}

export async function servers(page: Page): Promise<Server[]> {
  return (await (await page.request.get("/api/mcp")).json()).servers;
}

// Opens a new conversation that is given the servers named, and no others, since tests run beside each other on one
// server. It is titled at once, since the conversations of all the tests are listed on the side.
export async function openChat(page: Page, title: string, mcp: string[]): Promise<string> {
  const made = await page.request.post("/api/chats", { data: { title, mcp } });
  expect(made.status(), await made.text()).toBe(201);
  const id: string = (await made.json()).id;
  await page.goto(`/chat?id=${id}`);
  await expect(page.getByRole("button", { name: "Attach files" })).toBeEnabled();

  return id;
}

export async function say(page: Page, message: string): Promise<void> {
  await page.getByRole("textbox", { name: "Message" }).fill(message);
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByTestId("user-message").last()).toContainText(message);
}

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.once("error", reject);
    probe.listen(0, "127.0.0.1", () => {
      const { port } = probe.address() as net.AddressInfo;
      probe.close(() => resolve(port));
    });
  });
}

// The test server as a program of its own, reached over HTTP. With --oauth it is signed in to, with an authorization
// server that signs anyone in at once, as a browser would find once a person had signed in.
export class HttpServer {
  readonly port: number;
  private process: ChildProcess | null = null;

  private constructor(
    port: number,
    private readonly options: string[],
  ) {
    this.port = port;
  }

  // One that is not started, so that its address can be given to a server that is set up before it is there
  static async chosen(...options: string[]): Promise<HttpServer> {
    return new HttpServer(await freePort(), options);
  }

  static async started(...options: string[]): Promise<HttpServer> {
    const server = await HttpServer.chosen(...options);
    await server.start();

    return server;
  }

  get url(): string {
    return `http://127.0.0.1:${this.port}/mcp`;
  }

  // How a server of one's own that is this one is described
  get entry(): Record<string, unknown> {
    return { url: this.url, transport: "http", ...(this.options.includes("--oauth") ? { auth: "oauth" } : {}) };
  }

  // How many clients were registered, sign-ins made, and tokens refreshed
  async stats(): Promise<{ registered: number; signed_in: number; refreshed: number }> {
    return (await fetch(`http://127.0.0.1:${this.port}/oauth-stats`)).json();
  }

  async start(): Promise<void> {
    const child = spawn(PYTHON, [TEST_SERVER, ...this.options, "http", String(this.port)], { stdio: "ignore" });
    this.process = child;
    const stopped = new Promise<never>((_, reject) => child.once("exit", (code) => reject(new Error(`The test server stopped with ${code}`))));
    const deadline = Date.now() + 30_000;
    const listening = (async () => {
      while (Date.now() < deadline) {
        try {
          await this.stats();

          return;
        } catch {
          await new Promise((resolve) => setTimeout(resolve, 100));
        }
      }
      throw new Error(`The test server did not start on port ${this.port}`);
    })();
    await Promise.race([listening, stopped]);
  }

  stop(): void {
    this.process?.kill();
    this.process = null;
  }
}
