// Layout and visual regression guard for every screen.
//
// - At six widths from a small phone to a wide desktop, no screen may scroll
//   sideways: the bug the redesign's baseline found (a 375px header pushing
//   the page out to ~748px) must not come back.
// - At a phone and a desktop width, each screen must match its committed
//   screenshot. After an intended visual change, refresh the baselines with
//   `npx playwright test ui --update-snapshots` and review the diff.

import { expect, test } from "@playwright/test";

import { SCREENS, horizontalOverflow, prepare } from "./support/screens";

const WIDTHS = [320, 375, 768, 1024, 1440, 1920];
const SNAPSHOT_WIDTHS = new Set([375, 1440]);

for (const width of WIDTHS) {
  test.describe(`${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    for (const screen of SCREENS) {
      test(screen.name, async ({ page }) => {
        await prepare(page, screen);
        await screen.open(page);
        await page.waitForLoadState("networkidle");

        expect(await horizontalOverflow(page), "page scrolls sideways").toBeLessThanOrEqual(0);

        if (SNAPSHOT_WIDTHS.has(width)) {
          await expect(page).toHaveScreenshot(`${screen.name}-${width}.png`, {
            fullPage: screen.isFullPage,
          });
        }
      });
    }
  });
}
