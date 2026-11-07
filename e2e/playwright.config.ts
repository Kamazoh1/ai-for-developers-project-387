import { defineConfig } from "@playwright/test";

// `run.mjs` starts the servers and passes their address; run it through `mise run e2e`.
const baseURL = process.env.E2E_BASE_URL;
if (!baseURL) throw new Error("E2E_BASE_URL is not set: run the suite with `mise run e2e`");

export default defineConfig({
  testDir: "./tests",
  // One shared database and one calendar: scenarios must not race for the same slots.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL,
    locale: "ru-RU",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
