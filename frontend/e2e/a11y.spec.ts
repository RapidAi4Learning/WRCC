// Automated accessibility check (axe-core, WCAG 2.2 A + AA) of every screen,
// on a phone and on a desktop. Axe catches the mechanical failures — contrast,
// names, roles, landmarks; keyboard flow and focus order are covered by the
// component tests (Modal, TabList, UserMenu, dialogs).

import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { SCREENS, prepare } from "./support/screens";

const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

for (const width of [375, 1440]) {
  test.describe(`${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    for (const screen of SCREENS) {
      test(screen.name, async ({ page }) => {
        await prepare(page, screen);
        await screen.open(page);
        await page.waitForLoadState("networkidle");

        const { violations } = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
        const summary = violations.map(
          (violation) =>
            `${violation.id} (${violation.impact}): ${violation.help}\n` +
            violation.nodes
              .slice(0, 5)
              .map((node) => `    ${node.target.join(" ")} — ${node.failureSummary?.split("\n")[1]?.trim() ?? ""}`)
              .join("\n"),
        );
        expect(summary, summary.join("\n\n")).toEqual([]);
      });
    }
  });
}
