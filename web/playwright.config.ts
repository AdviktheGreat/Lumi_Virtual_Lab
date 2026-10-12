import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.E2E_PORT ?? 8799);
// The server of the tests that change what every conversation is made with, or what the server knows: the settings, the
// keys, and the scientists. The tests of the other server make conversations all the time, and would be made differently.
const ownPort = port + 1;
// The Python that has virtual-lab[server] installed, which is whatever is on the path unless it is told
const python = process.env.VIRTUAL_LAB_PYTHON ?? "python3";

const server = (at: number) => ({
  command: `${python} e2e/scripted_server.py --port ${at} --static-dir out`,
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
    { name: "chromium", testIgnore: "**/own-server/**", use: { ...devices["Desktop Chrome"] } },
    {
      name: "own-server",
      testMatch: "**/own-server/**/*.spec.ts",
      use: { ...devices["Desktop Chrome"], baseURL: `http://127.0.0.1:${ownPort}` },
    },
  ],
  webServer: [server(port), server(ownPort)],
});
