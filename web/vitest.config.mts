import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  // The dates a test expects are those of one time zone, whichever the machine is in
  test: { include: ["src/**/*.test.ts"], environment: "node", env: { TZ: "UTC" } },
});
