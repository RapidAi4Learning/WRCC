// Visual captures of every screen, in the states that matter, at three widths.
//
// Not a pass/fail regression test: it writes PNGs to `e2e/shots/<label>/` so
// two runs (before and after a UI change) can be compared side by side. It
// only runs when a label is given, so the normal smoke run stays fast:
//
//   PowerShell:  $env:SHOTS_LABEL="baseline"; npx playwright test visual
//   bash:        SHOTS_LABEL=baseline npx playwright test visual

import { expect, test, type Page } from "@playwright/test";

import { mockApi, signIn } from "./support/mockApi";

const LABEL = process.env.SHOTS_LABEL;
const WIDTHS = [375, 1024, 1440];
const BASE_URL = "http://localhost:3100";

test.skip(!LABEL, "Set SHOTS_LABEL to capture screenshots.");

async function shot(page: Page, name: string, width: number, fullPage = true) {
  await page.waitForLoadState("networkidle");
  await page.screenshot({
    path: `e2e/shots/${LABEL}/${name}-${width}.png`,
    fullPage,
    animations: "disabled",
  });
}

async function openGenerated(page: Page) {
  await page.goto("/generate");
  await page.locator("#topic").fill("Spring first aid enrolments in Griffith");
  await page.getByRole("checkbox", { name: "Instagram" }).check({ force: true });
  await page.getByRole("button", { name: /Generate 3 ideas/ }).click();
  await expect(page.getByText(BODIES_MARKER).first()).toBeVisible();
}

const BODIES_MARKER = /Spring is here/;

for (const width of WIDTHS) {
  test.describe(`${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    test.beforeEach(async ({ page }) => {
      await mockApi(page);
    });

    test("login", async ({ page }) => {
      await page.goto("/login");
      await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
      await shot(page, "01-login", width);
    });

    test.describe("signed in", () => {
      test.beforeEach(async ({ page }) => {
        await signIn(page, BASE_URL);
      });

      test("generate — empty", async ({ page }) => {
        await page.goto("/generate");
        await expect(page.getByText("Your ideas land here")).toBeVisible();
        await shot(page, "02-generate-empty", width);
      });

      test("generate — results", async ({ page }) => {
        await openGenerated(page);
        await shot(page, "03-generate-results", width);
      });

      test("media panel", async ({ page }) => {
        await openGenerated(page);
        await page.getByRole("button", { name: /Media/ }).first().click();
        await expect(page.getByRole("dialog", { name: "Post media" })).toBeVisible();
        await expect(page.getByText(/trainer demonstrating CPR/)).toBeVisible();
        await shot(page, "04-media-panel", width, false);
      });

      test("history — expanded row", async ({ page }) => {
        await page.goto("/history");
        await page.getByRole("button", { name: /Auslan for Beginners/ }).click();
        await expect(page.getByRole("link", { name: /View post/ })).toBeVisible();
        await shot(page, "05-history", width);
      });

      test("publish dialog", async ({ page }) => {
        await page.goto("/history");
        await page
          .getByRole("button", { name: /Spring first aid/ })
          .filter({ hasText: "Approved" })
          .click();
        await page.getByRole("button", { name: "Preview" }).click();
        await expect(page.getByRole("dialog", { name: "Publish to Facebook" })).toBeVisible();
        await expect(page.getByText("Ready to publish.")).toBeVisible();
        await shot(page, "06-publish-dialog", width, false);
      });

      test("catalog — sync review", async ({ page }) => {
        await page.goto("/catalog");
        await expect(page.getByText("Awaiting your review")).toBeVisible();
        await page.getByRole("button", { name: /^HLTAID011/ }).click();
        await expect(page.getByText("Griffith").first()).toBeVisible();
        await shot(page, "07-catalog", width);
      });

      test("settings", async ({ page }) => {
        await page.goto("/settings");
        await expect(page.getByText("WRCC Company Page")).toBeVisible();
        await shot(page, "08-settings", width);
      });

      test("ui kit", async ({ page }) => {
        await page.goto("/ui-kit");
        await expect(page.getByRole("heading", { name: "UI kit" })).toBeVisible();
        await shot(page, "09-ui-kit", width);
      });
    });
  });
}
