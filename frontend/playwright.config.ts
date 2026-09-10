import { defineConfig } from "@playwright/test";

// Exercises the frontend alone — no backend needed. The smoke spec covers the
// login gate; the UI specs render every screen against a canned API (see
// e2e/support/mockApi.ts). Full-stack flows are covered by backend
// integration tests.
export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  // One OS-specific baseline per screenshot, kept next to the specs.
  snapshotPathTemplate: "{testDir}/__snapshots__/{arg}-{platform}{ext}",
  expect: {
    toHaveScreenshot: {
      animations: "disabled",
      // Anti-aliasing noise, not layout: a real change moves far more.
      maxDiffPixelRatio: 0.01,
    },
  },
  use: {
    baseURL: "http://localhost:3100",
  },
  webServer: {
    command: "npx next dev -p 3100",
    url: "http://localhost:3100/login",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
