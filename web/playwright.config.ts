import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.E2E_PORT ?? 8799);
// The server of the tests that change what every conversation is made with, or what the server knows: the settings, the
// keys, and the scientists. The tests of the other server make conversations all the time, and would be made differently.
const ownPort = port + 1;
// The server of the tests of the setup, where Docker and the place the data lake is fetched from are stand-ins that the
// tests arrange, through the port after it (see e2e/setup/state.ts)
const setupPort = port + 2;
const controlPort = port + 3;
// The server of the tests of the MCP servers, which are set up on it and given to every conversation made there that is
// not told which to have, so no other test is run on it
const mcpPort = port + 4;
// The Python that has virtual-lab[server] installed, which is whatever is on the path unless it is told
const python = process.env.VIRTUAL_LAB_PYTHON ?? "python3";

const server = (at: number, options = "") => ({
  // The path is quoted, since a folder it is in may have a space in its name
  command: `"${python}" e2e/scripted_server.py --port ${at} --static-dir out ${options}`.trim(),
  url: `http://127.0.0.1:${at}/api/health`,
  // A server left over from another run would have its conversations in it
  reuseExistingServer: false,
  timeout: 60_000,
  stdout: "pipe" as const,
  stderr: "pipe" as const,
});

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", testIgnore: ["**/own-server/**", "**/setup/**", "**/mcp/**"], use: { ...devices["Desktop Chrome"] } },
    {
      name: "own-server",
      testMatch: "**/own-server/**/*.spec.ts",
      use: { ...devices["Desktop Chrome"], baseURL: `http://127.0.0.1:${ownPort}` },
    },
    {
      name: "mcp",
      testMatch: "**/mcp/**/*.spec.ts",
      use: { ...devices["Desktop Chrome"], baseURL: `http://127.0.0.1:${mcpPort}` },
    },
    {
      name: "setup",
      testMatch: "**/setup/**/*.spec.ts",
      // What they arrange is shared by all of them, so they are run one after another
      fullyParallel: false,
      use: { ...devices["Desktop Chrome"], baseURL: `http://127.0.0.1:${setupPort}` },
    },
  ],
  webServer: [server(port), server(ownPort), server(setupPort, `--setup-control-port ${controlPort}`), server(mcpPort)],
});
