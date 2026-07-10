import { defineConfig } from "@playwright/test";

// Smoke config: exercises the frontend alone (no backend needed) — the login
// gate and static rendering. Full-stack flows are covered by backend
// integration tests.
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://localhost:3100",
  },
  webServer: {
    command: "npx next dev -p 3100",
    url: "http://localhost:3100/login",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
