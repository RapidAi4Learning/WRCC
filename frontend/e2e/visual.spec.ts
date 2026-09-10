// Visual captures of every screen, in the states that matter, at six widths.
//
// Not a pass/fail regression test (that is ui.spec.ts): it writes PNGs to
// `e2e/shots/<label>/` so two runs — before and after a UI change — can be
// compared side by side. It only runs when a label is given:
//
//   PowerShell:  $env:SHOTS_LABEL="baseline"; npx playwright test visual
//   bash:        SHOTS_LABEL=baseline npx playwright test visual

import { test } from "@playwright/test";

import { SCREENS, prepare } from "./support/screens";

const LABEL = process.env.SHOTS_LABEL;
const WIDTHS = [320, 375, 768, 1024, 1440, 1920];

test.skip(!LABEL, "Set SHOTS_LABEL to capture screenshots.");

for (const width of WIDTHS) {
  test.describe(`${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    for (const screen of SCREENS) {
      test(screen.name, async ({ page }) => {
        await prepare(page, screen);
        await screen.open(page);
        await page.waitForLoadState("networkidle");
        await page.screenshot({
          path: `e2e/shots/${LABEL}/${screen.name}-${width}.png`,
          fullPage: screen.isFullPage,
          animations: "disabled",
        });
      });
    }
  });
}
